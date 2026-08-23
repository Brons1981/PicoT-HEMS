"""Simulate explicit delegated intents over complete independent daily paths."""

from __future__ import annotations

from datetime import timedelta

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import (
    DailyReferenceInterval,
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_simulator import (
    IndependentDailySimulator,
    ScenarioTimeline,
)

METHOD_VERSION = "independent-daily-intent-simulator:v1"


class IndependentDailyIntentSimulator:
    """Apply one complete physical intent schedule to every PV scenario."""

    def simulate(
        self,
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        intent_schedule: DailyReferenceIntentSchedule,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceSimulationSet:
        IndependentDailySimulator._validate_inputs(
            snapshot_id=snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
        )
        self._validate_schedule(snapshot_id, household, intent_schedule)
        trajectories = tuple(
            self._simulate_scenario(
                snapshot_id=snapshot_id,
                household=household,
                scenario=scenario,
                storage_state=storage_state,
                conversion_model=conversion_model,
                intent_schedule=intent_schedule,
                minimum_storage_energy_wh=minimum_storage_energy_wh,
                target_storage_energy_wh=target_storage_energy_wh,
                maximum_charge_input_power_w=maximum_charge_input_power_w,
                maximum_discharge_output_power_w=maximum_discharge_output_power_w,
            )
            for scenario in pv_scenarios
        )
        return DailyReferenceSimulationSet(
            simulation_id=f"daily-reference:{snapshot_id}:{intent_schedule.schedule_id}",
            snapshot_id=snapshot_id,
            trajectories=trajectories,
            observer_only=True,
            method_version=METHOD_VERSION,
        )

    def _simulate_scenario(
        self,
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        scenario: ScenarioTimeline,
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        intent_schedule: DailyReferenceIntentSchedule,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceTrajectory:
        loads = {(item.starts_at, item.ends_at): item for item in household.intervals}
        intents = {
            (item.starts_at, item.ends_at): item for item in intent_schedule.intervals
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
            intent = intents[(pv.starts_at, pv.ends_at)]
            start_energy_wh = stored_energy_wh
            duration_h = (pv.ends_at - pv.starts_at).total_seconds() / 3600.0
            charge_power_limit_wh = maximum_charge_input_power_w * duration_h
            discharge_power_limit_wh = maximum_discharge_output_power_w * duration_h

            pv_to_household_wh = min(pv.energy_wh, load.expected_energy_wh)
            pv_surplus_wh = pv.energy_wh - pv_to_household_wh
            household_deficit_wh = load.expected_energy_wh - pv_to_household_wh

            storage_to_household_wh = 0.0
            storage_to_grid_wh = 0.0
            pv_to_storage_wh = 0.0
            grid_to_storage_wh = 0.0
            charge_loss_wh = 0.0
            discharge_loss_wh = 0.0

            if intent.intent in {
                DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
                DailyStorageIntent.NOM,
                DailyStorageIntent.STORAGE_EXPORT,
            }:
                available_output_wh = max(
                    0.0, stored_energy_wh - minimum_storage_energy_wh
                ) * conversion_model.discharge_efficiency
                storage_to_household_wh = min(
                    household_deficit_wh,
                    available_output_wh,
                    discharge_power_limit_wh,
                )
                household_deficit_wh -= storage_to_household_wh
                available_output_wh -= storage_to_household_wh
                discharge_power_limit_wh -= storage_to_household_wh
                if intent.intent is DailyStorageIntent.STORAGE_EXPORT:
                    storage_to_grid_wh = min(
                        intent.storage_export_target_wh,
                        available_output_wh,
                        discharge_power_limit_wh,
                    )
                total_storage_output_wh = (
                    storage_to_household_wh + storage_to_grid_wh
                )
                removed_storage_wh = (
                    total_storage_output_wh / conversion_model.discharge_efficiency
                )
                discharge_loss_wh = removed_storage_wh - total_storage_output_wh
                stored_energy_wh -= removed_storage_wh

            if intent.intent in {
                DailyStorageIntent.NOM,
                DailyStorageIntent.GRID_REQUIREMENT,
            }:
                room_stored_wh = max(0.0, target_storage_energy_wh - stored_energy_wh)
                room_input_wh = room_stored_wh / conversion_model.charge_efficiency
                pv_to_storage_wh = min(
                    pv_surplus_wh,
                    charge_power_limit_wh,
                    room_input_wh,
                )
                remaining_charge_power_wh = charge_power_limit_wh - pv_to_storage_wh
                remaining_room_input_wh = room_input_wh - pv_to_storage_wh
                if intent.intent is DailyStorageIntent.GRID_REQUIREMENT:
                    grid_to_storage_wh = min(
                        remaining_charge_power_wh,
                        remaining_room_input_wh,
                    )
                total_charge_input_wh = pv_to_storage_wh + grid_to_storage_wh
                if (
                    target_reached_at is None
                    and total_charge_input_wh >= room_input_wh > 0.0
                ):
                    fraction = room_input_wh / total_charge_input_wh
                    target_reached_at = pv.starts_at + timedelta(
                        seconds=(pv.ends_at - pv.starts_at).total_seconds() * fraction
                    )
                charge_loss_wh = total_charge_input_wh * (
                    1.0 - conversion_model.charge_efficiency
                )
                stored_energy_wh += total_charge_input_wh - charge_loss_wh

            pv_to_grid_wh = pv_surplus_wh - pv_to_storage_wh
            evidence_ids = tuple(
                dict.fromkeys(
                    (
                        intent_schedule.schedule_id,
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
                    pv_to_storage_input_wh=pv_to_storage_wh,
                    pv_to_grid_wh=pv_to_grid_wh,
                    grid_to_household_wh=household_deficit_wh,
                    grid_to_storage_input_wh=grid_to_storage_wh,
                    storage_to_household_output_wh=storage_to_household_wh,
                    storage_charge_loss_wh=charge_loss_wh,
                    storage_discharge_loss_wh=discharge_loss_wh,
                    storage_energy_at_start_wh=start_energy_wh,
                    storage_energy_at_end_wh=stored_energy_wh,
                    confidence=min(pv.confidence, load.confidence, storage_state.confidence),
                    evidence_ids=evidence_ids,
                    storage_to_grid_output_wh=storage_to_grid_wh,
                )
            )
        return DailyReferenceTrajectory(
            trajectory_id=(
                f"daily-trajectory:{snapshot_id}:{intent_schedule.schedule_id}:"
                f"{scenario.scenario.value}"
            ),
            snapshot_id=snapshot_id,
            scenario=scenario.scenario,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            target_storage_energy_wh=target_storage_energy_wh,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_reached_at=target_reached_at,
            intervals=tuple(intervals),
            method_version=METHOD_VERSION,
            intent_schedule_id=intent_schedule.schedule_id,
        )

    @staticmethod
    def _validate_schedule(
        snapshot_id: str,
        household: HouseholdLoadForecast,
        schedule: DailyReferenceIntentSchedule,
    ) -> None:
        if schedule.snapshot_id != snapshot_id:
            raise ValueError("Daily intent and simulation snapshots must match.")
        if (
            schedule.horizon_start != household.horizon_start
            or schedule.horizon_end != household.horizon_end
        ):
            raise ValueError("Daily intent must cover the exact simulation horizon.")
        schedule_keys = tuple(
            (item.starts_at, item.ends_at) for item in schedule.intervals
        )
        household_keys = tuple(
            (item.starts_at, item.ends_at) for item in household.intervals
        )
        if schedule_keys != household_keys:
            raise ValueError("Daily intent and simulation intervals must align exactly.")
