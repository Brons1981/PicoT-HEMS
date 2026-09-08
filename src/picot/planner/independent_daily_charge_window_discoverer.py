"""Discover interval-minimal charge windows through physical simulation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from math import isfinite

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_charge_window import (
    DailyMainChargeSegment,
    DailyMainChargeWindow,
    DailyMainChargeWindowSet,
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
    DailyPlanningProjection,
    DailyReferenceSimulationSet,
    DailyReferenceTrajectory,
)
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_intent_simulator import (
    IndependentDailyIntentSimulator,
)
from picot.planner.independent_daily_simulator import ScenarioTimeline
from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyMainShortfallTrigger

METHOD_VERSION = "independent-daily-charge-window-discoverer:v5"
BASELINE_INTENT = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
CHARGE_INTENTS = (
    DailyStorageIntent.NOM,
    DailyStorageIntent.GRID_REQUIREMENT,
)


class IndependentDailyChargeWindowDiscoverer:
    """Use the simulator itself to derive sufficient minimal charge duration."""

    def discover_main_charge(
        self,
        *,
        snapshot_id: str,
        assignment: DailyChargeAssignment,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
        retained_schedule: DailyReferenceIntentSchedule | None = None,
        optimisation_trigger: DailyMainShortfallTrigger | None = None,
    ) -> DailyMainChargeWindowSet:
        """Discover the first main route under an existing daily identity.

        Candidate ownership only: all feasible market starts remain unranked.
        No prices, score, legacy deadline, micro-top-up suppression or trade
        recovery policy selects a winner here. The retained complete schedule
        is simulated unchanged outside this assignment's main segments.
        """
        if assignment.execution_scope_id != storage_state.execution_scope_id:
            raise ValueError("main assignment and storage scope must match")
        count = 0

        def result(
            windows: tuple[DailyMainChargeWindow, ...], status: str, reason: str
        ) -> DailyMainChargeWindowSet:
            return DailyMainChargeWindowSet(
                assignment.assignment_id, snapshot_id, windows, status, reason, count
            )

        if assignment.completed_at is not None:
            return result((), "completed", "observed_main_goal_already_completed")
        if optimisation_trigger is not None:
            optimisation_trigger.validate(assignment, snapshot_id, household.horizon_start)
        elif assignment.revision:
            raise ValueError(
                "existing main route requires explicit optimisation, not first discovery"
            )
        if not all(
            isfinite(x)
            for x in (
                target_storage_energy_wh,
                minimum_storage_energy_wh,
                maximum_charge_input_power_w,
                maximum_discharge_output_power_w,
                storage_state.usable_capacity_wh,
            )
        ):
            raise ValueError("main charge physical limits must be finite")
        if target_storage_energy_wh != storage_state.usable_capacity_wh:
            return result((), "unreachable", "configured_maximum_conflicts_with_daily_100_percent")
        baseline = retained_schedule or DailyReferenceIntentSchedule(
            schedule_id=f"main-charge:{snapshot_id}:retained-baseline",
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=tuple(
                DailyReferenceIntentInterval(i.starts_at, i.ends_at, BASELINE_INTENT)
                for i in household.intervals
            ),
            method_version="daily-main-charge:v1",
        )
        simulator = IndependentDailyIntentSimulator()

        def simulate(schedule: DailyReferenceIntentSchedule) -> DailyPlanningProjection:
            nonlocal count
            count += 1
            return simulator.simulate_planning_basis(
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

        reference = simulate(baseline)
        indexes = tuple(
            i
            for i, interval in enumerate(household.intervals)
            if assignment.starts_at <= interval.starts_at and interval.ends_at <= assignment.ends_at
        )
        if not indexes:
            return result((), "unreachable", "no_remaining_delivery_day_intervals")
        pv_indexes = tuple(
            i
            for i in indexes
            if reference.basis_timeline.intervals[i].energy_wh
            > household.intervals[i].expected_energy_wh
        )
        windows: dict[str, DailyMainChargeWindow] = {}

        def reached(
            projection: DailyPlanningProjection, owned: set[int]
        ) -> tuple[int, datetime] | None:
            for i in sorted(owned):
                interval = projection.intervals[i]
                # Numerical conservation tolerance, not a configurable SOC goal.
                if interval.storage_energy_at_start_wh + 1e-6 >= target_storage_energy_wh:
                    return i, interval.starts_at
                if interval.storage_energy_at_end_wh + 1e-6 >= target_storage_energy_wh:
                    return i, interval.ends_at
            return None

        def propose(owned: dict[int, DailyStorageIntent]) -> DailyReferenceIntentSchedule:
            intervals = tuple(
                replace(interval, intent=owned[i]) if i in owned else interval
                for i, interval in enumerate(baseline.intervals)
            )
            digest = sha256(repr((assignment.assignment_id, intervals)).encode()).hexdigest()[:16]
            return replace(
                baseline,
                schedule_id=f"main-charge:{snapshot_id}:{digest}",
                intervals=intervals,
                method_version="daily-main-charge:v1",
            )

        def admit(owned: dict[int, DailyStorageIntent], family: str) -> bool:
            projection = simulate(propose(owned))
            completion = reached(projection, set(owned))
            if completion is None:
                return False
            last, _ = completion
            owned = {i: intent for i, intent in owned.items() if i <= last}
            schedule = propose(owned)
            if schedule.schedule_id in windows:
                return True
            projection = simulate(schedule)
            completion = reached(projection, set(owned))
            if completion is None:
                raise ValueError("trimmed main route lost its full-storage evidence")
            segments: list[DailyMainChargeSegment] = []
            for i, intent in sorted(owned.items()):
                interval = schedule.intervals[i]
                if (
                    segments
                    and segments[-1].ends_at == interval.starts_at
                    and (segments[-1].intent is intent)
                ):
                    segments[-1] = replace(segments[-1], ends_at=interval.ends_at)
                else:
                    segments.append(
                        DailyMainChargeSegment(
                            f"{schedule.schedule_id}:main:{i}",
                            interval.starts_at,
                            interval.ends_at,
                            intent,
                        )
                    )
            windows[schedule.schedule_id] = DailyMainChargeWindow(
                assignment.assignment_id,
                family,
                schedule,
                tuple(segments),
                projection,
                completion[1],
                target_storage_energy_wh,
            )
            return True

        # A full battery at the first eligible main segment counts without a
        # forced discharge/recharge. Midnight outside the main segment does not.
        first = indexes[0]
        if (
            household.intervals[first].starts_at == household.horizon_start
            and storage_state.current_stored_energy_wh >= target_storage_energy_wh
        ):
            admit({first: DailyStorageIntent.NOM}, "already_full")
            return result(tuple(windows.values()), "discovered", "full_at_main_segment_start")
        for start in pv_indexes:
            if start != 0 and not self._is_market_quarter(household.intervals[start].starts_at):
                continue
            admit(
                {i: DailyStorageIntent.NOM for i in indexes if start <= i <= pv_indexes[-1]}, "pv"
            )
        if windows:
            return result(tuple(windows.values()), "discovered", "pv_only_covers_main_goal")

        # Keep PV capture as a base, and let explicit grid charging take
        # precedence inside its own interval, including during the PV window.
        pv_owned = {
            i: DailyStorageIntent.NOM
            for i in indexes
            if pv_indexes and pv_indexes[0] <= i <= pv_indexes[-1]
        }
        for start in indexes:
            if start != 0 and not self._is_market_quarter(household.intervals[start].starts_at):
                continue

            def owned_until(end: int, grid_start: int = start) -> dict[int, DailyStorageIntent]:
                return {
                    **pv_owned,
                    **{
                        i: DailyStorageIntent.GRID_REQUIREMENT
                        for i in indexes
                        if grid_start <= i <= end
                    },
                }

            last = indexes[-1]
            owned = owned_until(last)
            if reached(simulate(propose(owned)), set(owned)) is None:
                continue
            # Added grid intervals cannot reduce stored energy under these
            # intents. Binary search finds minimal grid duration for each start.
            low, high = start, last
            while low < high:
                middle = (low + high) // 2
                trial = owned_until(middle)
                if reached(simulate(propose(trial)), set(trial)) is not None:
                    high = middle
                else:
                    low = middle + 1
            admit(owned_until(low), "hybrid" if pv_owned else "grid")
        return result(
            tuple(windows.values()),
            "discovered" if windows else "unreachable",
            "residual_grid_windows" if windows else "insufficient_remaining_charge_capacity",
        )

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
        def intent_for_interval(index: int) -> DailyStorageIntent:
            """Keep forecast PV first and add only residual grid recovery."""

            if index < nom_end_index:
                return DailyStorageIntent.NOM
            if grid_start_index <= index < grid_end_index:
                return DailyStorageIntent.GRID_REQUIREMENT
            return BASELINE_INTENT

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
                    intent=intent_for_interval(index),
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
