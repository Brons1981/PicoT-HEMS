"""Value independent daily physical paths using explicit interval tariffs."""

from __future__ import annotations

from datetime import datetime

from picot.domain.daily_reference_financial import (
    DailyReferenceFinancialInterval,
    DailyReferenceFinancialPath,
    DailyReferenceFinancialSet,
)
from picot.domain.daily_reference_simulation import (
    DailyReferenceInterval,
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)

METHOD_VERSION = "independent-daily-financial-settlement:v1"


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
        tariff_by_interval = {
            (item.starts_at, item.ends_at): item for item in tariffs.intervals
        }
        paths = tuple(
            self._settle_path(
                trajectory=trajectory,
                tariffs=tariffs,
                tariff_by_interval=tariff_by_interval,
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
        tariff_by_interval: dict[
            tuple[datetime, datetime], DailyReferenceTariffInterval
        ],
    ) -> DailyReferenceFinancialPath:
        if (
            trajectory.horizon_start != tariffs.horizon_start
            or trajectory.horizon_end != tariffs.horizon_end
        ):
            raise ValueError("Daily tariff must cover the exact trajectory horizon.")
        settled: list[DailyReferenceFinancialInterval] = []
        for physical in trajectory.intervals:
            tariff = tariff_by_interval.get((physical.starts_at, physical.ends_at))
            if tariff is None:
                raise ValueError("Daily settlement requires an exact interval tariff.")
            settled.append(self._settle_interval(physical, tariff))
        intervals = tuple(settled)
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

    @staticmethod
    def _settle_interval(
        physical: DailyReferenceInterval,
        tariff: DailyReferenceTariffInterval,
    ) -> DailyReferenceFinancialInterval:
        grid_import_wh = physical.grid_to_household_wh + physical.grid_to_storage_input_wh
        grid_import_cost_eur = grid_import_wh * tariff.import_eur_per_kwh / 1000.0
        grid_export_result_eur = (
            (physical.pv_to_grid_wh + physical.storage_to_grid_output_wh)
            * tariff.export_eur_per_kwh
            / 1000.0
        )
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
            - opportunity_cost_eur
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
