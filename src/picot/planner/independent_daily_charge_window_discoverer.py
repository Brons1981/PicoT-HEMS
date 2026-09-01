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

METHOD_VERSION = "independent-daily-charge-window-discoverer:v4"
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
        micro_charge_suppression_fraction: float = 0.01,
        charge_session_active: bool = False,
        required_by: datetime | None = None,
    ) -> DailyReferenceChargeWindowSet:
        if not 0.0 <= micro_charge_suppression_fraction <= 1.0:
            raise ValueError("Daily micro-charge suppression fraction is invalid.")
        deadline = required_by or household.horizon_end
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError("Daily charge deadline must be timezone-aware.")
        if not household.horizon_start < deadline <= household.horizon_end:
            raise ValueError("Daily charge deadline must be inside the horizon.")
        starts_at_target = (
            storage_state.current_stored_energy_wh >= target_storage_energy_wh
        )
        target_gap_wh = max(
            0.0,
            target_storage_energy_wh - storage_state.current_stored_energy_wh,
        )
        if (
            not charge_session_active
            and target_gap_wh > 0.0
            and target_gap_wh
            <= storage_state.usable_capacity_wh * micro_charge_suppression_fraction
        ):
            baseline = self._schedule(
                snapshot_id=snapshot_id,
                household=household,
                intent=DailyStorageIntent.NOM,
                start_index=len(household.intervals),
                end_index=len(household.intervals),
                label="micro-charge-suppression-baseline",
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
            reserve_safe = all(
                all(
                    interval.storage_energy_at_end_wh + 1e-6
                    >= minimum_storage_energy_wh
                    for interval in trajectory.intervals
                )
                for trajectory in baseline_result.trajectories
            )
            if reserve_safe:
                return self._window_set(snapshot_id, (), status="not_required")
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
                if household.intervals[start_index].starts_at >= deadline:
                    continue
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
                if conservative > deadline:
                    continue
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
                sufficient_before_deadline = sufficient and all(
                    item <= deadline
                    for item in exact_reached
                    if item is not None
                )
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
                if not sufficient_before_deadline or shorter_sufficient:
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
        hybrid_schedules = self._discover_hybrid_schedules(
            snapshot_id=snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
            deadline=deadline,
            starts_at_target=starts_at_target,
            grid_start_times=tuple(
                item.starts_at
                for item in windows
                if item.intent is DailyStorageIntent.GRID_REQUIREMENT
            ),
        )
        return self._window_set(
            snapshot_id,
            tuple(windows),
            status="discovered" if windows else "no_feasible_window",
            hybrid_schedules=hybrid_schedules,
        )

    def _discover_hybrid_schedules(
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
        deadline: datetime,
        starts_at_target: bool,
        grid_start_times: tuple[datetime, ...],
    ) -> tuple[DailyReferenceIntentSchedule, ...]:
        """Build bounded PV-first paths with only the residual grid duration.

        NOM begins at the immutable horizon start and remains available through
        the last forecast interval that can contain PV surplus.  Each possible
        market-aligned grid start is then shortened through the physical
        lower/central/upper simulation until one fewer grid interval can no
        longer prove the target by the deadline.
        """

        potential_surplus_indexes = tuple(
            index
            for index, load in enumerate(household.intervals)
            if any(
                scenario.timeline.intervals[index].energy_wh
                > load.expected_energy_wh + 1e-6
                for scenario in pv_scenarios
            )
        )
        if not potential_surplus_indexes:
            return ()
        eligible_grid_starts = set(grid_start_times)
        nom_end_index = potential_surplus_indexes[-1] + 1
        schedules: list[DailyReferenceIntentSchedule] = []
        for start_index, interval in enumerate(household.intervals):
            if interval.starts_at not in eligible_grid_starts:
                continue
            if interval.starts_at >= deadline:
                continue
            if start_index != 0 and not self._is_market_quarter(interval.starts_at):
                continue
            probe = self._hybrid_schedule(
                snapshot_id=snapshot_id,
                household=household,
                nom_end_index=nom_end_index,
                grid_start_index=start_index,
                grid_end_index=len(household.intervals),
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
                    trajectory,
                    starts_at_target=starts_at_target,
                )
                for trajectory in probe_result.trajectories
            )
            if any(item is None or item > deadline for item in reached):
                continue
            target_times = tuple(item for item in reached if item is not None)
            conservative = max(target_times)
            end_index = next(
                index + 1
                for index, item in enumerate(household.intervals)
                if item.ends_at >= conservative
            )
            if end_index <= start_index or not self._is_market_quarter(
                household.intervals[end_index - 1].ends_at
            ):
                continue

            while end_index > start_index + 1:
                shorter = self._hybrid_schedule(
                    snapshot_id=snapshot_id,
                    household=household,
                    nom_end_index=nom_end_index,
                    grid_start_index=start_index,
                    grid_end_index=end_index - 1,
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
                    maximum_discharge_output_power_w=maximum_discharge_output_power_w,
                )
                shorter_reached = tuple(
                    self._recovery_target_reached_at(
                        trajectory,
                        starts_at_target=starts_at_target,
                    )
                    for trajectory in shorter_result.trajectories
                )
                if not all(
                    item is not None and item <= deadline
                    for item in shorter_reached
                ):
                    break
                end_index -= 1

            exact = self._hybrid_schedule(
                snapshot_id=snapshot_id,
                household=household,
                nom_end_index=nom_end_index,
                grid_start_index=start_index,
                grid_end_index=end_index,
                label="minimal",
            )
            if {
                DailyStorageIntent.NOM,
                DailyStorageIntent.GRID_REQUIREMENT,
            }.issubset({item.intent for item in exact.intervals}):
                schedules.append(exact)
        return tuple(schedules)

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
    def _hybrid_schedule(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        nom_end_index: int,
        grid_start_index: int,
        grid_end_index: int,
        label: str,
    ) -> DailyReferenceIntentSchedule:
        return DailyReferenceIntentSchedule(
            schedule_id=(
                f"daily-charge:{snapshot_id}:hybrid-pv-grid:"
                f"nom-end-{nom_end_index}:grid-start-{grid_start_index}:"
                f"grid-end-{grid_end_index}:{label}"
            ),
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=tuple(
                DailyReferenceIntentInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    intent=(
                        DailyStorageIntent.GRID_REQUIREMENT
                        if grid_start_index <= index < grid_end_index
                        else DailyStorageIntent.NOM
                        if index < nom_end_index
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
        hybrid_schedules: tuple[DailyReferenceIntentSchedule, ...] = (),
    ) -> DailyReferenceChargeWindowSet:
        return DailyReferenceChargeWindowSet(
            window_set_id=f"daily-charge-windows:{snapshot_id}",
            snapshot_id=snapshot_id,
            windows=windows,
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
            discovery_status=status,
            hybrid_schedules=hybrid_schedules,
        )
