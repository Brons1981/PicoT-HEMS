"""Discover interval-minimal charge windows through physical simulation."""

from __future__ import annotations

from datetime import datetime

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_charge_window import (
    DailyReferenceChargeWindow,
    DailyReferenceChargeWindowScenario,
    DailyReferenceChargeWindowSet,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import (
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_intent_simulator import (
    IndependentDailyIntentSimulator,
)
from picot.planner.independent_daily_simulator import ScenarioTimeline

METHOD_VERSION = "independent-daily-charge-window-discoverer:v3"
BASELINE_INTENT = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
CHARGE_INTENTS = (
    DailyStorageIntent.NOM,
    DailyStorageIntent.GRID_REQUIREMENT,
)


class IndependentDailyChargeWindowDiscoverer:
    """Use the simulator itself to derive sufficient minimal charge duration."""

    def discover(
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
        intents: tuple[DailyStorageIntent, ...] = CHARGE_INTENTS,
    ) -> DailyReferenceChargeWindowSet:
        starts_at_target = (
            storage_state.current_stored_energy_wh >= target_storage_energy_wh
        )
        if starts_at_target:
            baseline = self._schedule(
                snapshot_id=snapshot_id,
                household=household,
                intent=DailyStorageIntent.NOM,
                start_index=len(household.intervals),
                end_index=len(household.intervals),
                label="full-storage-baseline",
            )
            baseline_result = self._simulate(
                snapshot_id=snapshot_id,
                household=household,
                pv_scenarios=pv_scenarios,
                storage_state=storage_state,
                conversion_model=conversion_model,
                schedule=baseline,
                minimum_storage_energy_wh=minimum_storage_energy_wh,
                target_storage_energy_wh=target_storage_energy_wh,
                maximum_charge_input_power_w=maximum_charge_input_power_w,
                maximum_discharge_output_power_w=maximum_discharge_output_power_w,
            )
            if all(
                all(
                    interval.storage_energy_at_end_wh
                    >= target_storage_energy_wh
                    for interval in trajectory.intervals
                )
                for trajectory in baseline_result.trajectories
            ):
                return self._window_set(snapshot_id, (), status="not_required")
        windows: list[DailyReferenceChargeWindow] = []
        for intent in tuple(dict.fromkeys(intents)):
            if intent not in CHARGE_INTENTS:
                raise ValueError("Daily window discovery accepts only charge intents.")
            for start_index in range(len(household.intervals)):
                # The first interval starts at the immutable snapshot time and may
                # therefore be the remaining part of an already-running market
                # quarter. It is a valid immediate-start option. Future starts
                # remain aligned to exact market-quarter boundaries.
                if start_index != 0 and not self._is_market_quarter(
                    household.intervals[start_index].starts_at
                ):
                    continue
                probe = self._schedule(
                    snapshot_id=snapshot_id,
                    household=household,
                    intent=intent,
                    start_index=start_index,
                    end_index=len(household.intervals),
                    label="probe",
                )
                probe_result = self._simulate(
                    snapshot_id=snapshot_id,
                    household=household,
                    pv_scenarios=pv_scenarios,
                    storage_state=storage_state,
                    conversion_model=conversion_model,
                    schedule=probe,
                    minimum_storage_energy_wh=minimum_storage_energy_wh,
                    target_storage_energy_wh=target_storage_energy_wh,
                    maximum_charge_input_power_w=maximum_charge_input_power_w,
                    maximum_discharge_output_power_w=maximum_discharge_output_power_w,
                )
                reached = tuple(
                    self._recovery_target_reached_at(
                        item,
                        starts_at_target=starts_at_target,
                    )
                    for item in probe_result.trajectories
                )
                if any(item is None for item in reached):
                    continue
                target_times = tuple(item for item in reached if item is not None)
                conservative = max(target_times)
                end_index = next(
                    index + 1
                    for index, interval in enumerate(household.intervals)
                    if interval.ends_at >= conservative
                )
                if end_index <= start_index:
                    continue
                if not self._is_market_quarter(
                    household.intervals[end_index - 1].ends_at
                ):
                    continue
                schedule = self._schedule(
                    snapshot_id=snapshot_id,
                    household=household,
                    intent=intent,
                    start_index=start_index,
                    end_index=end_index,
                    label="minimal",
                )
                exact = self._simulate(
                    snapshot_id=snapshot_id,
                    household=household,
                    pv_scenarios=pv_scenarios,
                    storage_state=storage_state,
                    conversion_model=conversion_model,
                    schedule=schedule,
                    minimum_storage_energy_wh=minimum_storage_energy_wh,
                    target_storage_energy_wh=target_storage_energy_wh,
                    maximum_charge_input_power_w=maximum_charge_input_power_w,
                    maximum_discharge_output_power_w=maximum_discharge_output_power_w,
                )
                exact_reached = tuple(
                    self._recovery_target_reached_at(
                        item,
                        starts_at_target=starts_at_target,
                    )
                    for item in exact.trajectories
                )
                sufficient = all(item is not None for item in exact_reached)
                shorter_sufficient = False
                if end_index - start_index > 1:
                    shorter = self._schedule(
                        snapshot_id=snapshot_id,
                        household=household,
                        intent=intent,
                        start_index=start_index,
                        end_index=end_index - 1,
                        label="shorter",
                    )
                    shorter_result = self._simulate(
                        snapshot_id=snapshot_id,
                        household=household,
                        pv_scenarios=pv_scenarios,
                        storage_state=storage_state,
                        conversion_model=conversion_model,
                        schedule=shorter,
                        minimum_storage_energy_wh=minimum_storage_energy_wh,
                        target_storage_energy_wh=target_storage_energy_wh,
                        maximum_charge_input_power_w=maximum_charge_input_power_w,
                        maximum_discharge_output_power_w=(
                            maximum_discharge_output_power_w
                        ),
                    )
                    shorter_sufficient = all(
                        self._recovery_target_reached_at(
                            item,
                            starts_at_target=starts_at_target,
                        )
                        is not None
                        for item in shorter_result.trajectories
                    )
                if not sufficient or shorter_sufficient:
                    raise ValueError(
                        "Daily charge window minimality did not reconcile."
                    )
                outcomes_list: list[DailyReferenceChargeWindowScenario] = []
                for trajectory, reached_at in zip(
                    exact.trajectories,
                    exact_reached,
                    strict=True,
                ):
                    if reached_at is None:
                        raise ValueError("Daily charge window lost target evidence.")
                    outcomes_list.append(
                        DailyReferenceChargeWindowScenario(
                            scenario=trajectory.scenario,
                            target_reached_at=reached_at,
                        )
                    )
                outcomes = tuple(outcomes_list)
                windows.append(
                    DailyReferenceChargeWindow(
                        window_id=f"daily-charge-window:{schedule.schedule_id}",
                        intent=intent,
                        starts_at=household.intervals[start_index].starts_at,
                        ends_at=household.intervals[end_index - 1].ends_at,
                        interval_count=end_index - start_index,
                        scenario_outcomes=outcomes,
                        conservative_target_reached_at=max(
                            item.target_reached_at for item in outcomes
                        ),
                        schedule=schedule,
                        sufficient_across_scenarios=True,
                        one_interval_shorter_sufficient=False,
                        method_version=METHOD_VERSION,
                    )
                )
        return self._window_set(
            snapshot_id,
            tuple(windows),
            status="discovered" if windows else "no_feasible_window",
        )

    @staticmethod
    def _recovery_target_reached_at(
        trajectory: DailyReferenceTrajectory,
        *,
        starts_at_target: bool,
    ) -> datetime | None:
        if not starts_at_target:
            return trajectory.target_reached_at
        target = trajectory.target_storage_energy_wh
        fell_below_target = False
        for interval in trajectory.intervals:
            if (
                interval.storage_energy_at_start_wh < target
                or interval.storage_to_household_output_wh > 0.0
                or interval.storage_to_grid_output_wh > 0.0
            ):
                fell_below_target = True
            if fell_below_target and interval.storage_energy_at_end_wh >= target:
                return interval.ends_at
        return None

    @staticmethod
    def _is_market_quarter(value: datetime) -> bool:
        return (
            value.minute % 15 == 0
            and value.second == 0
            and value.microsecond == 0
        )

    @staticmethod
    def _schedule(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        intent: DailyStorageIntent,
        start_index: int,
        end_index: int,
        label: str,
    ) -> DailyReferenceIntentSchedule:
        return DailyReferenceIntentSchedule(
            schedule_id=(
                f"daily-charge:{snapshot_id}:{intent.value}:"
                f"start-{start_index}:end-{end_index}:{label}"
            ),
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=tuple(
                DailyReferenceIntentInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    intent=(
                        intent
                        if start_index <= index < end_index
                        else BASELINE_INTENT
                    ),
                )
                for index, item in enumerate(household.intervals)
            ),
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _simulate(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        schedule: DailyReferenceIntentSchedule,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceSimulationSet:
        return IndependentDailyIntentSimulator().simulate(
            snapshot_id=snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            conversion_model=conversion_model,
            intent_schedule=schedule,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
        )

    @staticmethod
    def _window_set(
        snapshot_id: str,
        windows: tuple[DailyReferenceChargeWindow, ...],
        *,
        status: str,
    ) -> DailyReferenceChargeWindowSet:
        return DailyReferenceChargeWindowSet(
            window_set_id=f"daily-charge-windows:{snapshot_id}",
            snapshot_id=snapshot_id,
            windows=windows,
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
            discovery_status=status,
        )
