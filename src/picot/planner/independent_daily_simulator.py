"""Independent physical NOM baseline over lower, central and upper PV scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_simulation import (
    DailyReferenceInterval,
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
    PVScenario,
)
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.pv_energy_timeline import PVEnergyTimeline
from picot.domain.storage_conversion_model import StorageConversionModel

METHOD_VERSION = "independent-daily-nom-simulator:v1"


@dataclass(frozen=True, slots=True)
class ScenarioTimeline:
    """One explicitly named PV uncertainty timeline."""

    scenario: PVScenario
    timeline: PVEnergyTimeline


class IndependentDailySimulator:
    """Simulate physical NOM without consuming current-pipeline Candidates."""

    def simulate(
        self,
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceSimulationSet:
        self._validate_inputs(
            snapshot_id=snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
        )
        trajectories = tuple(
            self._simulate_scenario(
                snapshot_id=snapshot_id,
                scenario=item,
                household=household,
                storage_state=storage_state,
                conversion_model=conversion_model,
                minimum_storage_energy_wh=minimum_storage_energy_wh,
                target_storage_energy_wh=target_storage_energy_wh,
                maximum_charge_input_power_w=maximum_charge_input_power_w,
                maximum_discharge_output_power_w=maximum_discharge_output_power_w,
            )
            for item in pv_scenarios
        )
        return DailyReferenceSimulationSet(
            simulation_id=f"daily-reference:{snapshot_id}",
            snapshot_id=snapshot_id,
            trajectories=trajectories,
            observer_only=True,
            method_version=METHOD_VERSION,
        )

    def _simulate_scenario(
        self,
        *,
        snapshot_id: str,
        scenario: ScenarioTimeline,
        household: HouseholdLoadForecast,
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceTrajectory:
        loads = {
            (item.starts_at, item.ends_at): item for item in household.intervals
        }
        stored_energy_wh = storage_state.current_stored_energy_wh
        target_reached_at = (
            household.horizon_start
            if stored_energy_wh >= target_storage_energy_wh
            else None
        )
        intervals: list[DailyReferenceInterval] = []
        for pv in scenario.timeline.intervals:
            load = loads[(pv.starts_at, pv.ends_at)]
            storage_energy_at_start_wh = stored_energy_wh
            duration_h = (pv.ends_at - pv.starts_at).total_seconds() / 3600.0

            pv_to_household_wh = min(pv.energy_wh, load.expected_energy_wh)
            pv_surplus_wh = pv.energy_wh - pv_to_household_wh
            remaining_household_wh = load.expected_energy_wh - pv_to_household_wh

            available_stored_input_wh = max(
                0.0, stored_energy_wh - minimum_storage_energy_wh
            )
            available_storage_output_wh = (
                available_stored_input_wh * conversion_model.discharge_efficiency
            )
            storage_to_household_wh = min(
                remaining_household_wh,
                available_storage_output_wh,
                maximum_discharge_output_power_w * duration_h,
            )
            storage_removed_wh = (
                storage_to_household_wh / conversion_model.discharge_efficiency
            )
            storage_discharge_loss_wh = storage_removed_wh - storage_to_household_wh
            stored_energy_wh -= storage_removed_wh
            remaining_household_wh -= storage_to_household_wh

            room_stored_wh = max(0.0, target_storage_energy_wh - stored_energy_wh)
            room_input_wh = room_stored_wh / conversion_model.charge_efficiency
            available_charge_input_wh = min(
                pv_surplus_wh,
                maximum_charge_input_power_w * duration_h,
            )
            pv_to_storage_input_wh = min(room_input_wh, available_charge_input_wh)
            if (
                target_reached_at is None
                and available_charge_input_wh >= room_input_wh > 0.0
            ):
                fraction = room_input_wh / available_charge_input_wh
                target_reached_at = pv.starts_at + timedelta(
                    seconds=(pv.ends_at - pv.starts_at).total_seconds() * fraction
                )
            storage_charge_loss_wh = pv_to_storage_input_wh * (
                1.0 - conversion_model.charge_efficiency
            )
            stored_energy_wh += pv_to_storage_input_wh - storage_charge_loss_wh
            pv_to_grid_wh = pv_surplus_wh - pv_to_storage_input_wh

            evidence_ids = tuple(
                dict.fromkeys(
                    (
                        scenario.timeline.timeline_id,
                        *pv.evidence_ids,
                        household.forecast_id,
                        storage_state.storage_state_id,
                        *storage_state.evidence_ids,
                        conversion_model.model_id,
                        *conversion_model.evidence_ids,
                    )
                )
            )
            intervals.append(
                DailyReferenceInterval(
                    starts_at=pv.starts_at,
                    ends_at=pv.ends_at,
                    household_demand_wh=load.expected_energy_wh,
                    usable_pv_wh=pv.energy_wh,
                    pv_to_household_wh=pv_to_household_wh,
                    pv_to_storage_input_wh=pv_to_storage_input_wh,
                    pv_to_grid_wh=pv_to_grid_wh,
                    grid_to_household_wh=remaining_household_wh,
                    grid_to_storage_input_wh=0.0,
                    storage_to_household_output_wh=storage_to_household_wh,
                    storage_charge_loss_wh=storage_charge_loss_wh,
                    storage_discharge_loss_wh=storage_discharge_loss_wh,
                    storage_energy_at_start_wh=storage_energy_at_start_wh,
                    storage_energy_at_end_wh=stored_energy_wh,
                    confidence=min(pv.confidence, load.confidence, storage_state.confidence),
                    evidence_ids=evidence_ids,
                )
            )

        return DailyReferenceTrajectory(
            trajectory_id=f"daily-trajectory:{snapshot_id}:{scenario.scenario.value}",
            snapshot_id=snapshot_id,
            scenario=scenario.scenario,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            target_storage_energy_wh=target_storage_energy_wh,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_reached_at=target_reached_at,
            intervals=tuple(intervals),
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _validate_inputs(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> None:
        if not snapshot_id.strip():
            raise ValueError("Daily simulation snapshot ID must be explicit.")
        scenarios = tuple(item.scenario for item in pv_scenarios)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("Daily simulation requires exactly lower, central and upper PV.")
        if not 0.0 <= minimum_storage_energy_wh <= target_storage_energy_wh:
            raise ValueError("Daily storage limits must be ordered and non-negative.")
        if target_storage_energy_wh > storage_state.usable_capacity_wh:
            raise ValueError("Daily storage target may not exceed usable capacity.")
        if maximum_charge_input_power_w <= 0.0:
            raise ValueError("Daily simulation requires positive maximum charge power.")
        if maximum_discharge_output_power_w <= 0.0:
            raise ValueError("Daily simulation requires positive maximum discharge power.")
        load_keys = tuple(
            (item.starts_at, item.ends_at) for item in household.intervals
        )
        for item in pv_scenarios:
            timeline = item.timeline
            if (
                timeline.horizon_start != household.horizon_start
                or timeline.horizon_end != household.horizon_end
            ):
                raise ValueError("Daily PV and household horizons must match exactly.")
            pv_keys = tuple(
                (interval.starts_at, interval.ends_at) for interval in timeline.intervals
            )
            if pv_keys != load_keys:
                raise ValueError("Daily PV and household intervals must align exactly.")
