"""Canonical timed storage-acquisition interval allocation from ADR-044."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil

from picot.domain.capability_snapshot import LogicalCapabilitySnapshot
from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.opportunity import Opportunity
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.domain.projected_household_energy_balance import ProjectedHouseholdEnergyBalance
from picot.domain.storage_energy_requirement import StorageEnergyRequirement

METHOD_VERSION = "timed-storage-acquisition-v1"
_EPSILON_WH = 1e-6


@dataclass(frozen=True, slots=True)
class SelectedAcquisitionInterval:
    """One exact source-price interval selected for grid-supported acquisition."""

    forecast_id: str
    point_index: int
    starts_at: datetime
    ends_at: datetime
    price_eur_per_kwh: float
    requested_power_w: float
    scheduled_energy_wh: float

    @property
    def projected_cost_eur(self) -> float:
        return self.scheduled_energy_wh / 1000.0 * self.price_eur_per_kwh

    @property
    def evidence_id(self) -> str:
        return f"{self.forecast_id}:point:{self.point_index}"


@dataclass(frozen=True, slots=True)
class TimedStorageAcquisitionAllocation:
    """Deterministic interval allocation selected from one price Opportunity."""

    opportunity_id: str
    requirement_id: str
    balance_id: str
    forecast_id: str
    intervals: tuple[SelectedAcquisitionInterval, ...]
    scheduled_grid_energy_wh: float
    projected_cost_eur: float
    projected_energy_at_protection_start_wh: float
    method_version: str = METHOD_VERSION


class TimedStorageAcquisitionAllocator:
    """Select exact Opportunity-backed price intervals without a parallel balance model."""

    def allocate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
        balance: ProjectedHouseholdEnergyBalance,
        requirement: StorageEnergyRequirement,
        storage_limit: EffectiveStorageLimit,
        capability: LogicalCapabilitySnapshot,
    ) -> TimedStorageAcquisitionAllocation | None:
        series, referenced = self._resolve_price_points(snapshot, opportunity)
        eligible = self._eligible_points(
            snapshot=snapshot,
            balance=balance,
            requirement=requirement,
            referenced=referenced,
        )
        if not eligible:
            return None

        baseline_at_protection = self._energy_at(
            balance, requirement.protection_starts_at
        )
        if baseline_at_protection is None:
            raise ValueError(
                "Canonical projected balance has no boundary at protection_starts_at."
            )
        deficit_wh = max(
            0.0, requirement.required_energy_wh - baseline_at_protection
        )
        if deficit_wh <= _EPSILON_WH:
            return None

        maximum_power_w = capability.maximum_power_w
        if maximum_power_w is None or maximum_power_w <= 0.0:
            raise ValueError("Storage capability has no usable maximum charge power.")

        scheduled: dict[tuple[str, int], float] = {}
        # Cost first. Equal-price intervals prefer the latest feasible start.
        ranked = sorted(
            eligible,
            key=lambda item: (
                item[1].value,
                -item[1].starts_at.timestamp(),
                item[0],
            ),
        )

        for point_index, point in ranked:
            duration_hours = (
                point.ends_at - point.starts_at
            ).total_seconds() / 3600.0
            maximum_energy_wh = maximum_power_w * duration_hours
            if maximum_energy_wh <= _EPSILON_WH:
                continue

            before = self._simulate_energy_at_protection(
                balance=balance,
                storage_limit=storage_limit,
                requirement=requirement,
                series=series,
                scheduled_energy_wh=scheduled,
            )
            trial = dict(scheduled)
            trial[(series.forecast_id, point_index)] = maximum_energy_wh
            after = self._simulate_energy_at_protection(
                balance=balance,
                storage_limit=storage_limit,
                requirement=requirement,
                series=series,
                scheduled_energy_wh=trial,
            )
            marginal_effect_wh = max(0.0, after - before)
            if marginal_effect_wh <= _EPSILON_WH:
                continue

            remaining_deficit_wh = max(
                0.0, requirement.required_energy_wh - before
            )
            if marginal_effect_wh + _EPSILON_WH < remaining_deficit_wh:
                scheduled = trial
                continue

            # With the canonical v1 energy accounting there are no private
            # conversion losses: useful scheduled Wh are one-for-one until the
            # effective storage ceiling is reached. Do not scale the final input
            # by a clipped full-power marginal effect; that would over-schedule.
            required_input_wh = remaining_deficit_wh
            requested_power_w = self._valid_power_for_energy(
                required_energy_wh=required_input_wh,
                duration_hours=duration_hours,
                capability=capability,
            )
            if requested_power_w is None:
                scheduled = trial
            else:
                scheduled[(series.forecast_id, point_index)] = (
                    requested_power_w * duration_hours
                )
            break

        projected_at_protection = self._simulate_energy_at_protection(
            balance=balance,
            storage_limit=storage_limit,
            requirement=requirement,
            series=series,
            scheduled_energy_wh=scheduled,
        )
        if projected_at_protection + _EPSILON_WH < requirement.required_energy_wh:
            return None

        selected: list[SelectedAcquisitionInterval] = []
        for point_index, point in sorted(
            eligible, key=lambda item: item[1].starts_at
        ):
            energy_wh = scheduled.get((series.forecast_id, point_index), 0.0)
            if energy_wh <= _EPSILON_WH:
                continue
            duration_hours = (
                point.ends_at - point.starts_at
            ).total_seconds() / 3600.0
            power_w = energy_wh / duration_hours
            selected.append(
                SelectedAcquisitionInterval(
                    forecast_id=series.forecast_id,
                    point_index=point_index,
                    starts_at=point.starts_at,
                    ends_at=point.ends_at,
                    price_eur_per_kwh=point.value,
                    requested_power_w=power_w,
                    scheduled_energy_wh=energy_wh,
                )
            )

        if not selected:
            return None
        total_energy = sum(item.scheduled_energy_wh for item in selected)
        total_cost = sum(item.projected_cost_eur for item in selected)
        return TimedStorageAcquisitionAllocation(
            opportunity_id=opportunity.opportunity_id,
            requirement_id=requirement.requirement_id,
            balance_id=balance.balance_id,
            forecast_id=series.forecast_id,
            intervals=tuple(selected),
            scheduled_grid_energy_wh=total_energy,
            projected_cost_eur=total_cost,
            projected_energy_at_protection_start_wh=projected_at_protection,
        )

    @staticmethod
    def _resolve_price_points(
        snapshot: PlanningInputSnapshot,
        opportunity: Opportunity,
    ) -> tuple[ForecastSeries, tuple[tuple[int, ForecastPoint], ...]]:
        price_by_id = {
            series.forecast_id: series
            for series in snapshot.forecasts.by_kind(ForecastKind.ENERGY_PRICE)
        }
        references = [
            reference
            for reference in opportunity.evidence
            if reference.source_id in price_by_id
        ]
        if len(references) != 1:
            raise ValueError(
                "Price Opportunity must resolve to exactly one ENERGY_PRICE ForecastSeries."
            )
        reference = references[0]
        series = price_by_id[reference.source_id]
        resolved: list[tuple[int, ForecastPoint]] = []
        for index in reference.point_indexes:
            if index >= len(series.points):
                raise ValueError(
                    "Price Opportunity references a missing ForecastPoint index."
                )
            resolved.append((index, series.points[index]))
        return series, tuple(resolved)

    @staticmethod
    def _eligible_points(
        *,
        snapshot: PlanningInputSnapshot,
        balance: ProjectedHouseholdEnergyBalance,
        requirement: StorageEnergyRequirement,
        referenced: tuple[tuple[int, ForecastPoint], ...],
    ) -> tuple[tuple[int, ForecastPoint], ...]:
        boundaries = {balance.created_at, *(point.at for point in balance.points)}
        eligible: list[tuple[int, ForecastPoint]] = []
        for index, point in referenced:
            if point.ends_at <= snapshot.captured_at:
                continue
            # A partially elapsed source interval is not privately resampled here.
            if point.starts_at < snapshot.captured_at:
                continue
            if point.ends_at > requirement.protection_starts_at:
                continue
            if point.starts_at not in boundaries or point.ends_at not in boundaries:
                raise ValueError(
                    "Price interval boundaries are not represented by the canonical "
                    "projected household balance."
                )
            eligible.append((index, point))
        return tuple(eligible)

    @staticmethod
    def _energy_at(
        balance: ProjectedHouseholdEnergyBalance,
        at: datetime,
    ) -> float | None:
        if at == balance.created_at:
            return balance.starting_storage_energy_wh
        for point in balance.points:
            if point.at == at:
                return point.projected_storage_energy_wh
        return None

    @staticmethod
    def _valid_power_for_energy(
        *,
        required_energy_wh: float,
        duration_hours: float,
        capability: LogicalCapabilitySnapshot,
    ) -> float | None:
        if duration_hours <= 0.0:
            return None
        maximum = capability.maximum_power_w
        if maximum is None:
            return None
        requested = required_energy_wh / duration_hours
        if capability.power_step_w is not None:
            requested = (
                ceil(requested / capability.power_step_w) * capability.power_step_w
            )
        if capability.minimum_power_w is not None:
            requested = max(requested, capability.minimum_power_w)
        if requested <= 0.0 or requested > maximum:
            return None
        return float(requested)

    @staticmethod
    def _simulate_energy_at_protection(
        *,
        balance: ProjectedHouseholdEnergyBalance,
        storage_limit: EffectiveStorageLimit,
        requirement: StorageEnergyRequirement,
        series: ForecastSeries,
        scheduled_energy_wh: dict[tuple[str, int], float],
    ) -> float:
        index_by_end = {
            point.ends_at: index for index, point in enumerate(series.points)
        }
        current_energy = balance.starting_storage_energy_wh
        previous_baseline = balance.starting_storage_energy_wh
        for point in balance.points:
            baseline_delta = point.projected_storage_energy_wh - previous_baseline
            current_energy += baseline_delta
            price_index = index_by_end.get(point.at)
            if price_index is not None:
                current_energy += scheduled_energy_wh.get(
                    (series.forecast_id, price_index), 0.0
                )
            current_energy = min(current_energy, storage_limit.max_energy_wh)
            if current_energy < -_EPSILON_WH:
                return current_energy
            previous_baseline = point.projected_storage_energy_wh
            if point.at == requirement.protection_starts_at:
                return current_energy
        raise ValueError("Protection start is outside the projected balance timeline.")
