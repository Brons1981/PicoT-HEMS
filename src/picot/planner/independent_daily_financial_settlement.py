"""Value independent daily physical paths using explicit interval tariffs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from picot.domain.daily_reference_financial import (
    DailyPlanningFinancialResult,
    DailyReferenceFinancialInterval,
    DailyReferenceFinancialPath,
    DailyReferenceFinancialSet,
)
from picot.domain.daily_reference_simulation import (
    DailyPlanningProjection,
    DailyReferenceInterval,
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)

METHOD_VERSION = "independent-daily-financial-settlement:v2"


class IndependentDailyFinancialSettlement:
    """Settle complete paths without ranking or changing physical allocation."""

    def settle(
        self,
        *,
        simulation: DailyReferenceSimulationSet,
        tariffs: DailyReferenceTariffSchedule,
    ) -> DailyReferenceFinancialSet:
        if tariffs.snapshot_id != simulation.snapshot_id:
            raise ValueError("Daily tariff and simulation snapshots must match.")
        tariffs_by_physical_interval = self._index_tariffs(
            simulation.trajectories[0].intervals,
            tariffs,
        )
        paths = tuple(
            self._settle_path(
                trajectory=trajectory,
                tariffs=tariffs,
                tariffs_by_physical_interval=tariffs_by_physical_interval,
            )
            for trajectory in simulation.trajectories
        )
        return DailyReferenceFinancialSet(
            financial_set_id=f"daily-financial:{simulation.simulation_id}",
            simulation_id=simulation.simulation_id,
            snapshot_id=simulation.snapshot_id,
            paths=paths,
            observer_only=True,
            selection_permitted=False,
            method_version=METHOD_VERSION,
        )

    def _settle_path(
        self,
        *,
        trajectory: DailyReferenceTrajectory,
        tariffs: DailyReferenceTariffSchedule,
        tariffs_by_physical_interval: dict[
            tuple[datetime, datetime], tuple[DailyReferenceTariffInterval, ...]
        ],
    ) -> DailyReferenceFinancialPath:
        if (
            trajectory.horizon_start != tariffs.horizon_start
            or trajectory.horizon_end != tariffs.horizon_end
        ):
            raise ValueError("Daily tariff must cover the exact trajectory horizon.")
        intervals = self._settle_intervals(
            trajectory.intervals, tariffs_by_physical_interval=tariffs_by_physical_interval)
        duration_hours = tuple(
            (item.ends_at - item.starts_at).total_seconds() / 3600.0
            for item in tariffs.intervals
        )
        total_hours = sum(duration_hours)
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    trajectory.trajectory_id,
                    tariffs.schedule_id,
                    *(
                        evidence
                        for interval in intervals
                        for evidence in interval.evidence_ids
                    ),
                )
            )
        )
        return DailyReferenceFinancialPath(
            financial_path_id=f"daily-financial-path:{trajectory.trajectory_id}",
            trajectory_id=trajectory.trajectory_id,
            snapshot_id=trajectory.snapshot_id,
            tariff_schedule_id=tariffs.schedule_id,
            scenario=trajectory.scenario,
            average_import_eur_per_kwh=sum(
                item.import_eur_per_kwh * hours
                for item, hours in zip(tariffs.intervals, duration_hours, strict=True)
            )
            / total_hours,
            average_export_eur_per_kwh=sum(
                item.export_eur_per_kwh * hours
                for item, hours in zip(tariffs.intervals, duration_hours, strict=True)
            )
            / total_hours,
            grid_import_cost_eur=sum(item.grid_import_cost_eur for item in intervals),
            grid_export_result_eur=sum(
                item.grid_export_result_eur for item in intervals
            ),
            avoided_import_value_eur=sum(
                item.avoided_import_value_eur for item in intervals
            ),
            pv_storage_opportunity_cost_eur=sum(
                item.pv_storage_opportunity_cost_eur for item in intervals
            ),
            conversion_loss_value_eur=sum(
                item.conversion_loss_value_eur for item in intervals
            ),
            net_financial_result_eur=sum(
                item.net_financial_result_eur for item in intervals
            ),
            confidence=min(item.confidence for item in intervals),
            intervals=intervals,
            evidence_ids=evidence_ids,
            method_version=METHOD_VERSION,
        )

    def settle_planning_basis(
        self,
        *,
        projection: DailyPlanningProjection,
        tariffs: DailyReferenceTariffSchedule,
        main_intervals: tuple[tuple[datetime, datetime], ...] | None = None,
    ) -> DailyPlanningFinancialResult:
        """Use the same interval settlement and fiscal allocation as scenarios."""
        if projection.snapshot_id != tariffs.snapshot_id:
            raise ValueError("planning tariff and projection snapshots must match")
        if (
            projection.basis_timeline.horizon_start != tariffs.horizon_start
            or projection.basis_timeline.horizon_end != tariffs.horizon_end
        ):
            raise ValueError("planning tariff must cover the exact projection horizon")
        indexed = self._index_tariffs(projection.intervals, tariffs)
        intervals = self._settle_intervals(
            projection.intervals, tariffs_by_physical_interval=indexed
        )
        owned = (
            main_intervals
            if main_intervals is not None
            else ((projection.basis_timeline.horizon_start, projection.basis_timeline.horizon_end),)
        )
        boundaries = {i.starts_at for i in projection.intervals} | {
            i.ends_at for i in projection.intervals
        }
        if any(
            start not in boundaries or end not in boundaries or start >= end for start, end in owned
        ):
            raise ValueError("main acquisition intervals must align with the physical projection")
        if any(a[1] > b[0] for a, b in zip(owned, owned[1:], strict=False)):
            raise ValueError("main acquisition intervals must be ordered and non-overlapping")
        input_wh = stored_wh = cost_eur = 0.0
        for physical in projection.intervals:
            if not any(
                start <= physical.starts_at and physical.ends_at <= end for start, end in owned
            ):
                continue
            input_wh += physical.pv_to_storage_input_wh + physical.grid_to_storage_input_wh
            stored_wh += (
                physical.pv_to_storage_input_wh
                + physical.grid_to_storage_input_wh
                - physical.storage_charge_loss_wh
            )
            for tariff in indexed[(physical.starts_at, physical.ends_at)]:
                part = self._physical_segment(
                    physical,
                    starts_at=max(physical.starts_at, tariff.starts_at),
                    ends_at=min(physical.ends_at, tariff.ends_at),
                )
                # PV's published export value is its acquisition opportunity
                # cost. Conversion loss is accounted once in stored Wh.
                cost_eur += (
                    part.grid_to_storage_input_wh * tariff.import_eur_per_kwh
                    + part.pv_to_storage_input_wh * tariff.export_eur_per_kwh
                ) / 1000
        return DailyPlanningFinancialResult(
            projection.snapshot_id,
            projection.intent_schedule_id,
            projection.basis_timeline.timeline_id,
            tariffs.schedule_id,
            intervals,
            METHOD_VERSION,
            input_wh,
            stored_wh,
            cost_eur,
        )

    def _settle_intervals(
        self,
        physical_intervals: tuple[DailyReferenceInterval, ...],
        *,
        tariffs_by_physical_interval: dict[
            tuple[datetime, datetime], tuple[DailyReferenceTariffInterval, ...]
        ],
    ) -> tuple[DailyReferenceFinancialInterval, ...]:
        physical_segments: list[tuple[DailyReferenceInterval, DailyReferenceTariffInterval]] = []
        for physical in physical_intervals:
            physical_tariffs = tariffs_by_physical_interval.get(
                (physical.starts_at, physical.ends_at)
            )
            if not physical_tariffs:
                raise ValueError("Daily settlement requires complete interval tariff coverage.")
            physical_segments.extend(
                (
                    self._physical_segment(
                        physical,
                        starts_at=max(physical.starts_at, tariff.starts_at),
                        ends_at=min(physical.ends_at, tariff.ends_at),
                    ),
                    tariff,
                )
                for tariff in physical_tariffs
            )
        saldering_import_wh = sum(
            max(0.0, self._grid_import_wh(physical) - self._grid_export_wh(physical))
            for physical, tariff in physical_segments
            if tariff.saldering_tax_eur_per_kwh > 0.0
        )
        saldering_export_wh = sum(
            max(0.0, self._grid_export_wh(physical) - self._grid_import_wh(physical))
            for physical, tariff in physical_segments
            if tariff.saldering_tax_eur_per_kwh > 0.0
        )
        remaining_saldering_wh = min(saldering_import_wh, saldering_export_wh)
        settled: list[DailyReferenceFinancialInterval] = []
        for physical, tariff in physical_segments:
            interval_export_wh = max(
                0.0,
                self._grid_export_wh(physical) - self._grid_import_wh(physical),
            )
            interval_saldering_wh = (
                min(remaining_saldering_wh, interval_export_wh)
                if tariff.saldering_tax_eur_per_kwh > 0.0
                else 0.0
            )
            settled.append(
                self._settle_interval(
                    physical,
                    tariff,
                    saldering_export_wh=interval_saldering_wh,
                )
            )
            remaining_saldering_wh -= interval_saldering_wh
        intervals = tuple(settled)
        return intervals

    @staticmethod
    def _index_tariffs(
        physical_intervals: tuple[DailyReferenceInterval, ...],
        tariffs: DailyReferenceTariffSchedule,
    ) -> dict[tuple[datetime, datetime], tuple[DailyReferenceTariffInterval, ...]]:
        result: dict[
            tuple[datetime, datetime], tuple[DailyReferenceTariffInterval, ...]
        ] = {}
        tariff_index = 0
        for physical in physical_intervals:
            while (
                tariff_index < len(tariffs.intervals)
                and tariffs.intervals[tariff_index].ends_at <= physical.starts_at
            ):
                tariff_index += 1
            overlapping: list[DailyReferenceTariffInterval] = []
            cursor = physical.starts_at
            scan_index = tariff_index
            while (
                scan_index < len(tariffs.intervals)
                and tariffs.intervals[scan_index].starts_at < physical.ends_at
            ):
                tariff = tariffs.intervals[scan_index]
                segment_start = max(physical.starts_at, tariff.starts_at)
                segment_end = min(physical.ends_at, tariff.ends_at)
                if segment_start != cursor or segment_end <= segment_start:
                    raise ValueError(
                        "Daily settlement requires complete interval tariff coverage."
                    )
                overlapping.append(tariff)
                cursor = segment_end
                if tariff.ends_at <= physical.ends_at:
                    scan_index += 1
                else:
                    break
            if cursor != physical.ends_at:
                raise ValueError(
                    "Daily settlement requires complete interval tariff coverage."
                )
            result[(physical.starts_at, physical.ends_at)] = tuple(overlapping)
        return result

    @staticmethod
    def _physical_segment(
        physical: DailyReferenceInterval,
        *,
        starts_at: datetime,
        ends_at: datetime,
    ) -> DailyReferenceInterval:
        total_seconds = (physical.ends_at - physical.starts_at).total_seconds()
        offset_fraction = (
            (starts_at - physical.starts_at).total_seconds() / total_seconds
        )
        fraction = (ends_at - starts_at).total_seconds() / total_seconds
        storage_delta_wh = (
            physical.storage_energy_at_end_wh
            - physical.storage_energy_at_start_wh
        )
        energy_fields = (
            "household_demand_wh",
            "usable_pv_wh",
            "pv_to_household_wh",
            "pv_to_storage_input_wh",
            "pv_to_grid_wh",
            "grid_to_household_wh",
            "grid_to_storage_input_wh",
            "storage_to_household_output_wh",
            "storage_charge_loss_wh",
            "storage_discharge_loss_wh",
            "storage_to_grid_output_wh",
        )
        return replace(
            physical,
            starts_at=starts_at,
            ends_at=ends_at,
            storage_energy_at_start_wh=(
                physical.storage_energy_at_start_wh
                + storage_delta_wh * offset_fraction
            ),
            storage_energy_at_end_wh=(
                physical.storage_energy_at_start_wh
                + storage_delta_wh * (offset_fraction + fraction)
            ),
            **{
                field: getattr(physical, field) * fraction
                for field in energy_fields
            },
        )

    @staticmethod
    def _grid_import_wh(physical: DailyReferenceInterval) -> float:
        return physical.grid_to_household_wh + physical.grid_to_storage_input_wh

    @staticmethod
    def _grid_export_wh(physical: DailyReferenceInterval) -> float:
        return physical.pv_to_grid_wh + physical.storage_to_grid_output_wh

    @staticmethod
    def _settle_interval(
        physical: DailyReferenceInterval,
        tariff: DailyReferenceTariffInterval,
        *,
        saldering_export_wh: float = 0.0,
    ) -> DailyReferenceFinancialInterval:
        grid_import_wh = IndependentDailyFinancialSettlement._grid_import_wh(physical)
        grid_export_wh = IndependentDailyFinancialSettlement._grid_export_wh(physical)
        grid_import_cost_eur = grid_import_wh * tariff.import_eur_per_kwh / 1000.0
        if tariff.cross_interval_export_eur_per_kwh is None:
            grid_export_result_eur = (
                grid_export_wh * tariff.export_eur_per_kwh / 1000.0
            )
        else:
            same_interval_wh = (
                min(grid_import_wh, grid_export_wh)
                if tariff.same_interval_offset_eur_per_kwh is not None
                else 0.0
            )
            cross_interval_export_wh = grid_export_wh - same_interval_wh
            grid_export_result_eur = (
                same_interval_wh
                * (
                    tariff.same_interval_offset_eur_per_kwh
                    if tariff.same_interval_offset_eur_per_kwh is not None
                    else 0.0
                )
                + cross_interval_export_wh
                * tariff.cross_interval_export_eur_per_kwh
                + min(saldering_export_wh, cross_interval_export_wh)
                * tariff.saldering_tax_eur_per_kwh
            ) / 1000.0
        avoided_import_value_eur = (
            physical.storage_to_household_output_wh
            * tariff.import_eur_per_kwh
            / 1000.0
        )
        opportunity_cost_eur = (
            physical.pv_to_storage_input_wh * tariff.export_eur_per_kwh / 1000.0
        )
        charge_input_wh = (
            physical.pv_to_storage_input_wh + physical.grid_to_storage_input_wh
        )
        pv_charge_share = (
            physical.pv_to_storage_input_wh / charge_input_wh
            if charge_input_wh > 0.0
            else 0.0
        )
        grid_charge_share = 1.0 - pv_charge_share if charge_input_wh > 0.0 else 0.0
        conversion_loss_value_eur = (
            physical.storage_charge_loss_wh
            * (
                pv_charge_share * tariff.export_eur_per_kwh
                + grid_charge_share * tariff.import_eur_per_kwh
            )
            + physical.storage_discharge_loss_wh * tariff.import_eur_per_kwh
        ) / 1000.0
        net_result_eur = (
            grid_export_result_eur
            + avoided_import_value_eur
            - grid_import_cost_eur
        )
        return DailyReferenceFinancialInterval(
            starts_at=physical.starts_at,
            ends_at=physical.ends_at,
            import_eur_per_kwh=tariff.import_eur_per_kwh,
            export_eur_per_kwh=tariff.export_eur_per_kwh,
            grid_import_cost_eur=grid_import_cost_eur,
            grid_export_result_eur=grid_export_result_eur,
            avoided_import_value_eur=avoided_import_value_eur,
            pv_storage_opportunity_cost_eur=opportunity_cost_eur,
            conversion_loss_value_eur=conversion_loss_value_eur,
            net_financial_result_eur=net_result_eur,
            confidence=min(physical.confidence, tariff.confidence),
            evidence_ids=tuple(dict.fromkeys((*physical.evidence_ids, *tariff.evidence_ids))),
        )
