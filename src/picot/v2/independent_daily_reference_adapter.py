"""Fail-closed adapter from shared v2 Planning Input to the daily simulator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    EnergyFlowDirection,
)
from picot.domain.current_storage_state import CurrentStorageState as DomainStorageState
from picot.domain.daily_reference_charge_window import (
    DailyMainChargeSegment,
    DailyMainChargeWindow,
    DailyMainChargeWindowSet,
    DailyReferenceChargeWindow,
    DailyReferenceChargeWindowSet,
    DailyRetainedMainSegment,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import (
    DailyPlanningProjection,
    DailyReferenceSimulationSet,
    PVScenario,
)
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.daily_reference_strategy_space import DailyReferenceStrategySpace
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffSchedule,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast as DomainHouseholdForecast,
)
from picot.domain.household_load_forecast import (
    HouseholdLoadForecastInterval as DomainHouseholdInterval,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimeline as DomainPVTimeline,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyTimelineInterval as DomainPVInterval,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator
from picot.planner.independent_daily_simulator import (
    IndependentDailySimulator,
    ScenarioTimeline,
)
from picot.planner.independent_daily_strategy_generator import (
    IndependentDailyStrategyGenerator,
)
from picot.planner.independent_daily_strategy_observer import (
    IndependentDailyStrategyObserver,
)
from picot.v2.contracts import (
    HouseholdLoadForecast,
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.daily_bridge import (
    DailyBridgeAssessment,
    DailyBridgeTrigger,
    energy_deficits,
    needs_bridge_review,
)
from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyMainShortfallTrigger
from picot.v2.daily_pv_comparison import DailyMainPVSurplusTrigger, DailyPVComparison
from picot.v2.independent_daily_tariff_adapter import (
    IndependentDailyTariffAdapter,
)
from picot.v2.plan_commitment_store import active_pv_preservation_dates
from picot.v2.supplemental_charge_planning import attach_supplemental_goals

METHOD_VERSION = "v2-independent-daily-reference-adapter:v7"
DAILY_REFERENCE_DURATION = timedelta(hours=24)


class DailyReferenceInputError(ValueError):
    """The shared snapshot cannot prove a complete independent simulation input."""


@dataclass(frozen=True, slots=True)
class _DailyReferenceInputs:
    household: DomainHouseholdForecast
    pv_scenarios: tuple[ScenarioTimeline, ...]
    storage: DomainStorageState
    minimum_storage_energy_wh: float
    target_storage_energy_wh: float
    maximum_charge_input_power_w: float
    maximum_discharge_output_power_w: float


class IndependentDailyReferenceAdapter:
    """Build and run the daily simulation without reading planner Candidates."""

    def bridge_assessment(
        self, *, snapshot: PlanningInputSnapshot, conversion_model: StorageConversionModel,
    ) -> DailyBridgeAssessment:
        context = snapshot.daily_charge_context
        if context is None or context.status != "ready":
            raise DailyReferenceInputError("bridge_recovery_context_blocked")
        completed = tuple(a for a in context.assignments if a.completed_at is not None)
        if not completed:
            return DailyBridgeAssessment("day_goal_not_completed")
        active = tuple(p for p in context.main_plans if p.plan_id in context.active_main_plan_ids)
        if len(active) != 1:
            return DailyBridgeAssessment("next_session_unknown")
        plan = active[0]
        future = sorted(
            ((s.starts_at, a) for a in context.assignments
             if a.completed_at is None and a.execution_scope_id == plan.execution_scope_id
             for s in a.main_segments if s.starts_at > snapshot.captured_at
             and any(p.main_assignment_id == a.assignment_id
                     and p.starts_at <= s.starts_at < p.ends_at for p in plan.segments)),
            key=lambda item: (item[0], item[1].assignment_id),
        )
        if any(s.starts_at <= snapshot.captured_at < s.ends_at for a in context.assignments
               if a.completed_at is None for s in a.main_segments):
            return DailyBridgeAssessment("main_session_active")
        if not future:
            # No invented deadline: expose only the known remaining trajectory.
            owner = next(a for a in context.assignments if a.route_plan_id == plan.plan_id)
            inputs = self._inputs(snapshot, horizon_end=plan.valid_until,
                                  maximum_duration=timedelta(hours=36))
            schedule, _ = self._retained_main_schedule(
                snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
            )
            assert schedule is not None
            projection = self._bridge_projection(snapshot, inputs, schedule, conversion_model)
            return DailyBridgeAssessment("next_session_unknown", deficits=energy_deficits(
                projection, schedule, until=plan.valid_until,
                maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
            ))
        until, owner = future[0]
        previous = tuple(a for a in completed if a.execution_scope_id == owner.execution_scope_id
                         and a.delivery_date < owner.delivery_date)
        if not previous:
            return DailyBridgeAssessment("day_goal_not_completed")
        inputs = self._inputs(snapshot, horizon_end=plan.valid_until,
                              maximum_duration=timedelta(hours=36))
        schedule, _ = self._retained_main_schedule(
            snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
        )
        assert schedule is not None
        projection = self._bridge_projection(snapshot, inputs, schedule, conversion_model)
        deficits = energy_deficits(projection, schedule, until=until,
                                   maximum_discharge_output_power_w=
                                   inputs.maximum_discharge_output_power_w)
        state = next((s for s in context.bridge_states if s.assignment_id == owner.assignment_id),
                     None)
        needed = needs_bridge_review(deficits, state, plan_id=plan.plan_id, next_starts_at=until)
        missed_goal = next((a for a in context.supplemental_assignments
                           if a.completed_at is None and a.next_assignment_id == owner.assignment_id
                           and a.required_by > snapshot.captured_at and not any(
                               a.starts_at <= i.ends_at <= min(a.ends_at, a.required_by)
                               and i.storage_energy_at_end_wh + 1e-6
                               >= a.target_soc * inputs.storage.usable_capacity_wh
                               for i in projection.intervals)), None)
        # Recovery can prove an earlier main completed while a later retry is
        # still scheduled. Reconcile through the existing candidate/evaluation
        # path, keeping the next main and independently assessing the bridge.
        recovered_ids = {a.assignment_id for a in completed
                         if a.historical_completion_segment is not None}
        obsolete_retry = any(s.main_assignment_id in recovered_ids
                             and s.ends_at > snapshot.captured_at for s in plan.segments)
        needed = needed or missed_goal is not None or obsolete_retry
        trigger = None
        if needed:
            assert owner.route_plan_id is not None
            trigger = DailyBridgeTrigger(
                owner.assignment_id, owner.route_plan_id, owner.revision, plan.plan_id,
                snapshot.snapshot_id, snapshot.captured_at, inputs.storage.usable_capacity_wh,
                max(previous, key=lambda a: a.delivery_date).assignment_id, until, deficits,
                missed_goal.assignment_id if missed_goal is not None else None,
                next(iter(sorted(recovered_ids))) if obsolete_retry else None,
            )
            trigger.validate(owner, snapshot.snapshot_id, snapshot.captured_at)
        return DailyBridgeAssessment(
            "completion_reconciliation" if obsolete_retry else
            "energy_shortfall" if needed else "accepted_grid_support" if state else "sufficient",
            owner.assignment_id, until, deficits, trigger,
        )

    @staticmethod
    def _bridge_projection(
        snapshot: PlanningInputSnapshot, inputs: _DailyReferenceInputs,
        schedule: DailyReferenceIntentSchedule, conversion_model: StorageConversionModel,
    ) -> DailyPlanningProjection:
        return IndependentDailyIntentSimulator().simulate_planning_basis(
            snapshot_id=snapshot.snapshot_id, household=inputs.household,
            pv_scenarios=inputs.pv_scenarios, storage_state=inputs.storage,
            conversion_model=conversion_model, intent_schedule=schedule,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )

    def bridge_windows(
        self, *, snapshot: PlanningInputSnapshot, trigger: DailyBridgeTrigger,
        conversion_model: StorageConversionModel,
    ) -> DailyMainChargeWindowSet:
        """Supplement the retained route; never discover a replacement main window."""
        context = snapshot.daily_charge_context
        assert context is not None
        owner = next(a for a in context.assignments if a.assignment_id == trigger.assignment_id)
        trigger.validate(owner, snapshot.snapshot_id, snapshot.captured_at)
        active = next(p for p in context.main_plans if p.plan_id == trigger.active_plan_id)
        inputs = self._inputs(snapshot, horizon_end=active.valid_until,
                              maximum_duration=timedelta(hours=36))
        baseline, retained = self._retained_main_schedule(
            snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
        )
        assert baseline is not None
        owned = tuple(r for r in retained if r.assignment_id == owner.assignment_id)
        others = tuple(r for r in retained if r.assignment_id != owner.assignment_id)
        free = tuple(n for n, i in enumerate(baseline.intervals)
                     if i.ends_at <= trigger.next_starts_at and not any(
                         r.segment.starts_at < i.ends_at and i.starts_at < r.segment.ends_at
                         for r in retained))
        if trigger.historical_completion_id is not None and not any(
            i.deficit_wh > 1e-6 for i in trigger.deficits
        ):
            # A missing completion record alone is no new acquisition need.
            free = ()
        schedules = {baseline.intervals: baseline}
        simulations = 0
        projections: dict[str, DailyPlanningProjection] = {}

        def add(intents: tuple[DailyReferenceIntentInterval, ...]) -> DailyReferenceIntentSchedule:
            schedule = replace(baseline, intervals=intents,
                               schedule_id="bridge:" + sha256(
                                   (snapshot.snapshot_id + repr(intents)).encode()
                               ).hexdigest()[:16])
            schedules.setdefault(intents, schedule)
            return schedules[intents]

        def project(schedule: DailyReferenceIntentSchedule) -> DailyPlanningProjection:
            nonlocal simulations
            if schedule.schedule_id not in projections:
                projections[schedule.schedule_id] = self._bridge_projection(
                    snapshot, inputs, schedule, conversion_model,
                )
                simulations += 1
            return projections[schedule.schedule_id]

        # PV capture over the bridge, individual controllable intervals, and
        # minimum sufficient contiguous charging from each feasible start.
        # The same interval simulator evaluates all options; no ranking takes place here.
        pv = tuple(replace(i, intent=DailyStorageIntent.NOM) if n in free else i
                   for n, i in enumerate(baseline.intervals))
        add(pv)
        # Direct grid support can preserve storage across a complete published
        # constant-price run, not merely one isolated simulation interval.
        runs: list[list[int]] = []
        previous_price: float | None = None
        for n in free:
            interval = baseline.intervals[n]
            price = next((p.value_eur_per_kwh for p in snapshot.price_points
                          if p.starts_at <= interval.starts_at and interval.ends_at <= p.ends_at),
                         None)
            if not runs or n != runs[-1][-1] + 1 or price != previous_price:
                runs.append([])
            runs[-1].append(n)
            previous_price = price
        for run in (*runs, list(free)):
            add(tuple(replace(i, intent=DailyStorageIntent.STANDBY)
                      if n in run else i for n, i in enumerate(pv)))
        for n in free:
            for intent in (DailyStorageIntent.GRID_REQUIREMENT, DailyStorageIntent.STANDBY):
                add(tuple(replace(i, intent=intent) if k == n else i for k, i in enumerate(pv)))
            consecutive: list[int] = []
            for end in free[free.index(n):]:
                if consecutive and end != consecutive[-1] + 1:
                    break
                consecutive.append(end)
            lo, hi = 1, len(consecutive)
            while lo < hi:
                mid = (lo + hi) // 2
                trial = add(tuple(replace(i, intent=DailyStorageIntent.GRID_REQUIREMENT)
                                  if k in consecutive[:mid] else i for k, i in enumerate(pv)))
                deficit = energy_deficits(project(trial), trial, until=trigger.next_starts_at,
                                          maximum_discharge_output_power_w=
                                          inputs.maximum_discharge_output_power_w)
                if any(i.deficit_wh > 1e-6 for i in deficit):
                    lo = mid + 1
                else:
                    hi = mid
            add(tuple(replace(i, intent=DailyStorageIntent.GRID_REQUIREMENT)
                      if k in consecutive[:lo] else i for k, i in enumerate(pv)))
        windows = []
        for schedule in schedules.values():
            projection = project(schedule)
            reaches = {}
            for a in context.assignments:
                if (a.completed_at is not None or not a.main_segments
                        or a.ends_at <= snapshot.captured_at):
                    continue
                reached = next((at for main in a.main_segments for i in projection.intervals
                                for at, energy in ((i.starts_at, i.storage_energy_at_start_wh),
                                                   (i.ends_at, i.storage_energy_at_end_wh))
                                if main.starts_at <= at <= main.ends_at
                                and energy + 1e-6 >= inputs.storage.usable_capacity_wh), None)
                if reached is None:
                    break
                reaches[a.assignment_id] = reached
            else:
                main = tuple(DailyMainChargeSegment(
                    "bridge-main:" + sha256((schedule.schedule_id + r.segment.segment_id)
                                            .encode()).hexdigest()[:16],
                    r.segment.starts_at, r.segment.ends_at,
                    DailyStorageIntent.GRID_REQUIREMENT
                    if r.segment.primitive is ExecutionPrimitive.CHARGE_AT_POWER
                    else DailyStorageIntent.NOM,
                ) for r in owned)
                windows.append(DailyMainChargeWindow(
                    owner.assignment_id, "hybrid", schedule, main, projection,
                    reaches[owner.assignment_id], inputs.storage.usable_capacity_wh, others,
                ))
        windows = [attached for w in windows if (attached := attach_supplemental_goals(
            w, snapshot, trigger)) is not None]
        return DailyMainChargeWindowSet(
            owner.assignment_id, snapshot.snapshot_id, tuple(windows),
            "discovered" if windows else "unreachable", "reserve_bridge_alternatives",
            simulations, purpose="bridge",
        )

    def main_route_shortfalls(
        self, *, snapshot: PlanningInputSnapshot, conversion_model: StorageConversionModel,
    ) -> tuple[DailyMainShortfallTrigger, ...]:
        """Simulate the retained route once; no tariff settlement or window search."""
        context = snapshot.daily_charge_context
        if context is None or context.status != "ready":
            raise DailyReferenceInputError("main_charge_recovery_context_blocked")
        pending = tuple(a for a in context.assignments if a.route_plan_id is not None
                        and a.completed_at is None and a.ends_at > snapshot.captured_at)
        if not pending:
            return ()
        active = tuple(p for p in context.main_plans if p.plan_id in context.active_main_plan_ids)
        if len(active) != 1:
            raise DailyReferenceInputError("main_charge_active_plan_required_for_monitoring")
        plan = active[0]
        inputs = self._inputs(snapshot, horizon_end=plan.valid_until,
                              maximum_duration=timedelta(hours=36))
        schedule, _ = self._retained_main_schedule(
            snapshot=snapshot, assignment=pending[0], inputs=inputs, supplied=None,
        )
        assert schedule is not None
        projection = IndependentDailyIntentSimulator().simulate_planning_basis(
            snapshot_id=snapshot.snapshot_id, household=inputs.household,
            pv_scenarios=inputs.pv_scenarios, storage_state=inputs.storage,
            conversion_model=conversion_model, intent_schedule=schedule,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )
        triggers = []
        for owner in pending:
            energies = [energy for main in owner.main_segments for interval in projection.intervals
                        for at, energy in (
                            (interval.starts_at, interval.storage_energy_at_start_wh),
                            (interval.ends_at, interval.storage_energy_at_end_wh),
                        )
                        if main.starts_at <= at <= main.ends_at]
            peak = max(energies, default=0.0)
            if peak + 1e-6 < inputs.storage.usable_capacity_wh:
                assert owner.route_plan_id is not None
                triggers.append(DailyMainShortfallTrigger(
                    owner.assignment_id, owner.route_plan_id, owner.revision, plan.plan_id,
                    snapshot.snapshot_id, snapshot.captured_at, peak,
                    inputs.storage.usable_capacity_wh,
                ))
        owners = {a.assignment_id: a for a in pending}
        return tuple(sorted(triggers, key=lambda t: (
            owners[t.assignment_id].delivery_date, owners[t.assignment_id].execution_scope_id,
            t.assignment_id,
        )))

    def pv_surplus_trigger(
        self, *, snapshot: PlanningInputSnapshot, assignment: DailyChargeAssignment,
        comparison: DailyPVComparison, conversion_model: StorageConversionModel,
    ) -> DailyMainPVSurplusTrigger | None:
        """Prove a removable future grid interval before any price window search."""
        if comparison.assignment_id != assignment.assignment_id or (
            comparison.status != "complete" or comparison.boundary != "above_central"
            or assignment.completed_at is not None or assignment.route_plan_id is None
        ):
            return None
        context = snapshot.daily_charge_context
        if context is None or context.status != "ready":
            raise DailyReferenceInputError("main_charge_recovery_context_blocked")
        active = tuple(p for p in context.main_plans if p.plan_id in context.active_main_plan_ids)
        if len(active) != 1:
            raise DailyReferenceInputError("main_charge_active_plan_required_for_monitoring")
        plan = active[0]
        grid = tuple(s for s in plan.segments if s.main_assignment_id == assignment.assignment_id
                     and s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
                     and s.ends_at > snapshot.captured_at)
        if not grid:
            return None
        if any(s.requested_power_w is None for s in grid):
            raise DailyReferenceInputError("retained_grid_power_unavailable")
        prior_grid_wh = sum(
            float(s.requested_power_w) * (s.ends_at - max(s.starts_at, snapshot.captured_at))
            .total_seconds() / 3600 for s in grid if s.requested_power_w is not None
        )
        inputs = self._inputs(snapshot, horizon_end=plan.valid_until,
                              maximum_duration=timedelta(hours=36))
        schedule, _ = self._retained_main_schedule(
            snapshot=snapshot, assignment=assignment, inputs=inputs, supplied=None,
        )
        assert schedule is not None
        pending = tuple(a for a in context.assignments if a.route_plan_id is not None
                        and a.completed_at is None and a.ends_at > snapshot.captured_at)
        for index in reversed(range(len(schedule.intervals))):
            interval = schedule.intervals[index]
            if not any(s.starts_at <= interval.starts_at and interval.ends_at <= s.ends_at
                       for s in grid):
                continue
            trial = replace(schedule, schedule_id=f"pv-grid-removal:{snapshot.snapshot_id}:{index}",
                            intervals=tuple(replace(i, intent=DailyStorageIntent.NOM)
                                            if n == index else i
                                            for n, i in enumerate(schedule.intervals)))
            projection = IndependentDailyIntentSimulator().simulate_planning_basis(
                snapshot_id=snapshot.snapshot_id, household=inputs.household,
                pv_scenarios=inputs.pv_scenarios, storage_state=inputs.storage,
                conversion_model=conversion_model, intent_schedule=trial,
                minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
                target_storage_energy_wh=inputs.target_storage_energy_wh,
                maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
                maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
            )
            if all(any(
                main.starts_at <= at <= main.ends_at
                and energy + 1e-6 >= inputs.storage.usable_capacity_wh
                for main in owner.main_segments for i in projection.intervals
                for at, energy in ((i.starts_at, i.storage_energy_at_start_wh),
                                   (i.ends_at, i.storage_energy_at_end_wh))
            ) for owner in pending):
                assert comparison.actual_wh is not None and comparison.central_wh is not None
                return DailyMainPVSurplusTrigger(
                    assignment.assignment_id, assignment.route_plan_id, assignment.revision,
                    plan.plan_id, snapshot.snapshot_id, snapshot.captured_at,
                    inputs.storage.usable_capacity_wh, comparison.basis_id, comparison.evidence_id,
                    comparison.actual_wh, comparison.central_wh, prior_grid_wh,
                    inputs.maximum_charge_input_power_w
                    * (interval.ends_at - interval.starts_at).total_seconds() / 3600,
                )
        return None

    def main_charge_windows(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        assignment: DailyChargeAssignment,
        conversion_model: StorageConversionModel,
        retained_schedule: DailyReferenceIntentSchedule | None = None,
        optimisation_trigger: DailyMainShortfallTrigger | DailyMainPVSurplusTrigger | None = None,
    ) -> DailyMainChargeWindowSet:
        """Canonical input seam for first main-route Candidate construction.

        The daily obligation does not truncate the household simulation. The
        complete published horizon (up to 36 hours) remains in every candidate.
        Selection and binding to an execution plan belong downstream.
        """
        if assignment.completed_at is not None:
            return DailyMainChargeWindowSet(
                assignment.assignment_id, snapshot.snapshot_id, (), "completed",
                "observed_main_goal_already_completed", 0)
        if optimisation_trigger is not None:
            optimisation_trigger.validate(assignment, snapshot.snapshot_id, snapshot.captured_at)
        elif assignment.revision:
            raise DailyReferenceInputError("main_charge_existing_route_requires_optimisation")
        if snapshot.horizon_end is None:
            raise DailyReferenceInputError("daily_reference_horizon_missing")
        maximum_end = min(snapshot.horizon_end, snapshot.captured_at + timedelta(hours=36))
        tariff_adapter = IndependentDailyTariffAdapter()
        published_end = tariff_adapter.published_horizon_end(
            snapshot, maximum_horizon_end=maximum_end
        )
        if assignment.ends_at > published_end:
            raise DailyReferenceInputError("main_charge_delivery_day_prices_incomplete")
        # Validate prices through their existing owner, including gaps/overlaps;
        # Candidate discovery does not infer or manufacture tariff values.
        tariff_adapter.build(snapshot, horizon_end=published_end)
        inputs = self._inputs(
            snapshot, horizon_end=published_end, maximum_duration=timedelta(hours=36)
        )
        retained_schedule, retained_main = self._retained_main_schedule(
            snapshot=snapshot, assignment=assignment, inputs=inputs,
            supplied=retained_schedule,
            revising_assignment_id=assignment.assignment_id if optimisation_trigger else None,
        )
        result = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
            snapshot_id=snapshot.snapshot_id,
            assignment=assignment,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
            retained_schedule=retained_schedule,
            optimisation_trigger=optimisation_trigger,
        )
        windows = tuple(
            replace(window, retained_main_segments=retained_main) for window in result.windows
        )
        context = snapshot.daily_charge_context
        pending = tuple(
            owner for owner in (context.assignments if context is not None else ())
            if owner.route_plan_id is not None and owner.completed_at is None
            and owner.execution_scope_id == assignment.execution_scope_id
            and owner.ends_at > snapshot.captured_at
            and (optimisation_trigger is None or owner.assignment_id != assignment.assignment_id)
        )
        # Correct one day at a time. A later route that was already insufficient
        # keeps its owner and gets its own turn; it cannot veto this day's repair.
        # Healthy retained goals and all earlier goals still have to remain feasible.
        deferred_ids: set[str] = set()
        if isinstance(optimisation_trigger, DailyMainShortfallTrigger) and pending:
            # Use monitoring of the complete active route, not the discovery
            # baseline where the selected owner's actions have been removed.
            existing_shortfalls = {t.assignment_id for t in self.main_route_shortfalls(
                snapshot=snapshot, conversion_model=conversion_model,
            )}
            deferred_ids = {
                owner.assignment_id for owner in pending
                if owner.delivery_date > assignment.delivery_date
                and owner.assignment_id in existing_shortfalls
            }
        feasible = tuple(window for window in windows if all(
            any(
                (
                    main.starts_at <= interval.starts_at < main.ends_at
                    and interval.storage_energy_at_start_wh + 1e-6
                    >= inputs.target_storage_energy_wh
                ) or (
                    main.starts_at < interval.ends_at <= main.ends_at
                    and interval.storage_energy_at_end_wh + 1e-6 >= inputs.target_storage_energy_wh
                )
                for main in owner.main_segments for interval in window.projection.intervals
            ) for owner in pending if owner.assignment_id not in deferred_ids
        ))
        if windows and not feasible:
            return replace(result, windows=(), status="unreachable",
                           reason="retained_main_goal_requires_explicit_optimisation")
        if isinstance(optimisation_trigger, DailyMainPVSurplusTrigger):
            feasible = tuple(w for w in feasible if sum(
                (i.ends_at - i.starts_at).total_seconds() / 3600
                * inputs.maximum_charge_input_power_w
                for i in w.main_segments if i.intent is DailyStorageIntent.GRID_REQUIREMENT
            ) < optimisation_trigger.prior_grid_input_wh - 1e-6)
            if not feasible:
                return replace(result, windows=(), status="unreachable",
                               reason="pv_comparison_has_no_admissible_grid_reduction")
        feasible = tuple(attached for w in feasible
                         if (attached := attach_supplemental_goals(w, snapshot)) is not None)
        return replace(result, windows=feasible) if feasible else replace(
            result, windows=(), status="unreachable", reason="supplemental_goal_unreachable"
        )

    @staticmethod
    def _retained_main_schedule(
        *, snapshot: PlanningInputSnapshot, assignment: DailyChargeAssignment,
        inputs: _DailyReferenceInputs, supplied: DailyReferenceIntentSchedule | None,
        revising_assignment_id: str | None = None,
    ) -> tuple[DailyReferenceIntentSchedule | None, tuple[DailyRetainedMainSegment, ...]]:
        context = snapshot.daily_charge_context
        if context is None:
            return supplied, ()
        if context.status != "ready":
            raise DailyReferenceInputError("main_charge_recovery_context_blocked")
        if assignment not in context.assignments:
            raise DailyReferenceInputError("main_charge_assignment_not_in_planning_input")
        owners = tuple(
            a for a in context.assignments
            if a.execution_scope_id == assignment.execution_scope_id and a.route_plan_id is not None
        )
        if not owners:
            return supplied, ()
        plans = {p.plan_id: p for p in context.main_plans}
        retained = []
        for owner in owners:
            if owner.historical_completion_segment is not None:
                continue
            assert owner.route_plan_id is not None
            plan = plans[owner.route_plan_id]
            if plan.created_at > snapshot.captured_at:
                raise DailyReferenceInputError("retained_main_plan_is_from_future_input")
            for main in owner.main_segments:
                if owner.assignment_id == revising_assignment_id:
                    continue
                source = next((s for s in plan.segments if s.segment_id == main.segment_id), None)
                if source is None or (source.starts_at, source.ends_at) != (
                    main.starts_at, main.ends_at,
                ):
                    raise DailyReferenceInputError("retained_main_segment_ownership_mismatch")
                if (
                    source.ends_at > snapshot.captured_at
                    and source.starts_at < inputs.household.horizon_end
                ):
                    retained.append(DailyRetainedMainSegment(
                        owner.assignment_id, plan.plan_id, source,
                    ))
        intents = {
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL: DailyStorageIntent.NOM,
            ExecutionPrimitive.CHARGE_AT_POWER: DailyStorageIntent.GRID_REQUIREMENT,
            ExecutionPrimitive.BALANCE_DISCHARGE_ONLY: DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
            ExecutionPrimitive.STANDBY: DailyStorageIntent.STANDBY,
            ExecutionPrimitive.DISCHARGE_AT_POWER: DailyStorageIntent.STORAGE_EXPORT,
        }
        intervals = []
        for grid in inputs.household.intervals:
            export_wh = 0.0
            retained_main = next((r for r in retained if r.segment.starts_at <= grid.starts_at
                                  and grid.ends_at <= r.segment.ends_at), None)
            intent = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
            sources = []
            source_plans = tuple(
                p for p in plans.values() if p.plan_id in context.active_main_plan_ids
            ) or tuple(plans.values())
            for plan in source_plans:
                if plan.valid_from >= grid.ends_at or plan.valid_until <= grid.starts_at:
                    continue
                part = next((s for s in plan.segments if s.starts_at <= grid.starts_at
                             and grid.ends_at <= s.ends_at), None)
                if part is None:
                    raise DailyReferenceInputError("retained_main_plan_has_a_schedule_gap")
                recovered = next((a for a in context.assignments
                                  if a.assignment_id == part.main_assignment_id
                                  and a.historical_completion_segment is not None), None)
                if recovered is not None:
                    part = replace(part, primitive=ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                                   requested_power_w=None, charge_source_policy=None,
                                   main_assignment_id=None, retained_execution_origin=None)
                sources.append(part)
            # Explicit main ownership overrides an older horizon's unowned
            # baseline. Otherwise retained plans must agree; never guess which
            # conflicting command is more desirable from price or chronology.
            if retained_main is None and sources and any(
                any(getattr(s, field) != getattr(sources[0], field) for field in (
                    "primitive", "capability_id", "requested_power_w", "charge_source_policy",
                    "soc_constraint", "energy_profile_id",
                )) for s in sources[1:]
            ):
                raise DailyReferenceInputError("retained_plans_disagree_outside_main_segments")
            retained_source = (
                retained_main.segment if retained_main is not None
                else sources[0] if sources else None
            )
            if retained_source is not None:
                source = retained_source
                if source.primitive not in intents:
                    raise DailyReferenceInputError("retained_main_primitive_not_simulatable")
                if source.primitive is ExecutionPrimitive.CHARGE_AT_POWER and (
                    source.requested_power_w != inputs.maximum_charge_input_power_w
                ):
                    raise DailyReferenceInputError(
                        "retained_charge_power_requires_explicit_revision"
                    )
                intent = intents[source.primitive]
                if intent is DailyStorageIntent.STORAGE_EXPORT:
                    bindings = tuple(b for b in context.market_plan_bindings
                                     if source.segment_id in b.segment_ids)
                    if len(bindings) != 1:
                        raise DailyReferenceInputError("retained_market_energy_binding_missing")
                    binding = bindings[0]
                    stopped = any(
                        p.assignment_id == binding.assignment_id and p.stop_requested_at is not None
                        for p in context.market_execution_progress
                    )
                    if stopped:
                        intent = DailyStorageIntent.NOM
                    else:
                        energy = binding.segment_export_wh[
                            binding.segment_ids.index(source.segment_id)
                        ]
                        export_wh = energy * (
                            (grid.ends_at - grid.starts_at).total_seconds()
                            / (source.ends_at - source.starts_at).total_seconds()
                        )
                if revising_assignment_id is not None and (
                    source.main_assignment_id == revising_assignment_id
                ):
                    intent = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
            intervals.append(DailyReferenceIntentInterval(
                grid.starts_at, grid.ends_at, intent, storage_export_target_wh=export_wh,
            ))
        schedule = DailyReferenceIntentSchedule(
            schedule_id="retained-main:" + sha256(
                (snapshot.snapshot_id + "|" + "|".join(sorted(plans))).encode()
            ).hexdigest()[:16],
            snapshot_id=snapshot.snapshot_id,
            horizon_start=inputs.household.horizon_start,
            horizon_end=inputs.household.horizon_end,
            intervals=tuple(intervals),
            method_version="daily-main-retained-schedule:v1",
        )
        if supplied is not None and supplied.intervals != schedule.intervals:
            raise DailyReferenceInputError("supplied_schedule_conflicts_with_stored_main_route")
        return schedule, tuple(retained)

    def simulate(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
    ) -> DailyReferenceSimulationSet:
        inputs = self._inputs(snapshot)
        return IndependentDailySimulator().simulate(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )

    def observe(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        tariffs: DailyReferenceTariffSchedule | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
        micro_charge_suppression_fraction: float = 0.01,
        required_by: datetime | None = None,
        preferred_grid_windows: tuple[tuple[datetime, datetime], ...] = (),
        preserve_pv_during_grid_charge: bool = False,
        saldering_energy_tax_credit_enabled: bool = True,
    ) -> DailyReferenceStrategyObservation:
        """Run the complete observer chain from one immutable Planning Input."""

        maximum_horizon_end = snapshot.captured_at + maximum_duration
        if tariffs is None:
            tariff_adapter = IndependentDailyTariffAdapter()
            published_horizon_end = tariff_adapter.published_horizon_end(
                snapshot,
                maximum_horizon_end=maximum_horizon_end,
            )
            inputs = self._inputs(
                snapshot,
                horizon_end=published_horizon_end,
                maximum_duration=maximum_duration,
            )
            tariffs = tariff_adapter.build(
                snapshot,
                horizon_end=published_horizon_end,
                saldering_energy_tax_credit_enabled=(
                    saldering_energy_tax_credit_enabled
                ),
            )
        else:
            inputs = self._inputs(
                snapshot,
                horizon_end=tariffs.horizon_end,
                maximum_duration=maximum_duration,
            )
        self._validate_tariffs(snapshot, inputs.household, tariffs)
        charge_windows = IndependentDailyChargeWindowDiscoverer().discover(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            charge_session_active=(
                snapshot.storage_mode_capability_evidence is not None
                and snapshot.storage_mode_capability_evidence.current_vendor_mode
                in {"Nul op de meter", "Snel opladen"}
            ),
            required_by=required_by,
        )
        if charge_windows.discovery_status == "no_feasible_window":
            raise DailyReferenceInputError("daily_reference_charge_windows_unavailable")
        charge_windows = self._select_representative_charge_paths(
            charge_windows,
            tariffs=tariffs,
            required_by=required_by,
            preferred_grid_windows=preferred_grid_windows,
            preserve_pv_during_grid_charge=preserve_pv_during_grid_charge,
        )
        strategy_space = IndependentDailyStrategyGenerator().generate_from_charge_windows(
            charge_windows=charge_windows,
            household=inputs.household,
        )
        if charge_windows.hybrid_schedules:
            # A hybrid supersedes only the isolated grid component.  The
            # physically complete PV-only path must remain independently
            # evaluable; otherwise merely discovering residual grid charging
            # removes the cheaper PV-first alternative from the portfolio.
            component_schedule_ids = {
                item.schedule.schedule_id
                for item in charge_windows.windows
                if item.intent is DailyStorageIntent.GRID_REQUIREMENT
            }
            strategy_space = replace(
                strategy_space,
                schedules=tuple(
                    item
                    for item in strategy_space.schedules
                    if item.schedule_id not in component_schedule_ids
                ),
            )
        if preserve_pv_during_grid_charge:
            strategy_space = self._preserve_pv_across_grid_charge_days(
                strategy_space,
                snapshot=snapshot,
                charge_windows=charge_windows,
                pv_scenarios=inputs.pv_scenarios,
            )
        pv_capture_schedule = self._pv_capture_schedule(
            snapshot_id=snapshot.snapshot_id,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
        )
        if (
            strategy_space.charge_requirement_status == "required"
            and pv_capture_schedule is not None
            and all(
                item.intervals != pv_capture_schedule.intervals for item in strategy_space.schedules
            )
        ):
            strategy_space = replace(
                strategy_space,
                schedules=(*strategy_space.schedules, pv_capture_schedule),
                active_intents=tuple(
                    dict.fromkeys((*strategy_space.active_intents, DailyStorageIntent.NOM))
                ),
            )
        return IndependentDailyStrategyObserver().observe(
            strategy_space=strategy_space,
            household=inputs.household,
            pv_scenarios=inputs.pv_scenarios,
            storage_state=inputs.storage,
            conversion_model=conversion_model,
            tariffs=tariffs,
            minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
            target_storage_energy_wh=inputs.target_storage_energy_wh,
            maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
            maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
        )

    @staticmethod
    def _preserve_pv_across_grid_charge_days(
        strategy_space: DailyReferenceStrategySpace,
        *,
        snapshot: PlanningInputSnapshot,
        charge_windows: DailyReferenceChargeWindowSet,
        pv_scenarios: tuple[ScenarioTimeline, ...],
    ) -> DailyReferenceStrategySpace:
        """Project the User Rule onto every bounded path for the same day.

        Candidate Generation already selected at most one residual-grid path.
        Its grid day is therefore a deterministic boundary: every existing
        candidate keeps storage bidirectional wherever the Solcast upper
        scenario still permits PV on that day. Explicit grid charge and export
        remain overlays. No schedules, routes, or timing alternatives are added.
        """

        grid_days = {
            interval.starts_at.date()
            for schedule in charge_windows.hybrid_schedules
            for interval in schedule.intervals
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        }
        grid_days.update(
            day
            for commitment in snapshot.active_plan_commitments
            for day in active_pv_preservation_dates(
                commitment,
                captured_at=snapshot.captured_at,
            )
        )
        if not grid_days:
            return strategy_space
        upper = next(item for item in pv_scenarios if item.scenario is PVScenario.UPPER)

        def possible_pv(interval: DailyReferenceIntentInterval) -> bool:
            return interval.starts_at.date() in grid_days and any(
                pv.energy_wh > 1e-6
                and interval.starts_at < pv.ends_at
                and interval.ends_at > pv.starts_at
                for pv in upper.timeline.intervals
            )

        schedules: list[DailyReferenceIntentSchedule] = []
        for schedule in strategy_space.schedules:
            intervals = tuple(
                replace(interval, intent=DailyStorageIntent.NOM)
                if possible_pv(interval)
                and interval.intent
                not in {
                    DailyStorageIntent.GRID_REQUIREMENT,
                    DailyStorageIntent.STORAGE_EXPORT,
                }
                else interval
                for interval in schedule.intervals
            )
            schedules.append(
                replace(
                    schedule,
                    schedule_id=(
                        f"{schedule.schedule_id}:preserve-pv-day"
                        if intervals != schedule.intervals
                        else schedule.schedule_id
                    ),
                    intervals=intervals,
                )
            )
        return replace(strategy_space, schedules=tuple(schedules))

    @classmethod
    def _select_representative_charge_paths(
        cls,
        charge_windows: DailyReferenceChargeWindowSet,
        *,
        tariffs: DailyReferenceTariffSchedule,
        required_by: datetime | None,
        preferred_grid_windows: tuple[tuple[datetime, datetime], ...],
        preserve_pv_during_grid_charge: bool = False,
    ) -> DailyReferenceChargeWindowSet:
        """Reduce physical alternatives before complete portfolio simulation.

        ADR-017/024 require confidence and economic relevance to reduce the
        search space before full simulation.  The physical discoverer may
        prove many interval-minimal starts; MEP retains the PV-only path with
        the lowest foregone export value plus one cheapest residual-grid path.
        A hybrid path supersedes pure grid charging when it exists.
        """

        if charge_windows.discovery_status != "discovered":
            return charge_windows

        nom_windows = tuple(
            item for item in charge_windows.windows if item.intent is DailyStorageIntent.NOM
        )
        grid_windows = tuple(
            item
            for item in charge_windows.windows
            if item.intent is DailyStorageIntent.GRID_REQUIREMENT
        )
        selected_nom = min(
            nom_windows,
            key=lambda item: (
                cls._nom_schedule_cost(item.schedule, tariffs),
                -item.starts_at.timestamp(),
                item.window_id,
            ),
            default=None,
        )
        preferred_hybrids = tuple(
            item
            for item in charge_windows.hybrid_schedules
            if cls._starts_in_preferred_window(cls._grid_start(item), preferred_grid_windows)
        )
        eligible_hybrids = preferred_hybrids or charge_windows.hybrid_schedules
        selected_hybrid = min(
            eligible_hybrids,
            key=lambda item: (
                cls._grid_schedule_cost(item, tariffs),
                -cls._grid_start(item).timestamp(),
                item.schedule_id,
            ),
            default=None,
        )
        if selected_hybrid is not None and preserve_pv_during_grid_charge:
            selected_hybrid = cls._preserve_pv_around_grid_charge(selected_hybrid)
        preferred_grid = tuple(
            item
            for item in grid_windows
            if cls._starts_in_preferred_window(item.starts_at, preferred_grid_windows)
        )
        eligible_grid = preferred_grid or grid_windows
        selected_grid = (
            min(eligible_grid, key=lambda item: item.starts_at, default=None)
            if required_by is None and selected_hybrid is None
            else max(
                eligible_grid,
                key=lambda item: (item.starts_at, item.window_id),
                default=None,
            )
            if not preferred_grid_windows
            else min(
                eligible_grid,
                key=lambda item: (
                    cls._grid_schedule_cost(item.schedule, tariffs),
                    -item.starts_at.timestamp(),
                    item.window_id,
                ),
                default=None,
            )
        )

        retained_windows: list[DailyReferenceChargeWindow] = []
        if selected_nom is not None:
            retained_windows.append(selected_nom)
        # The WindowSet contract retains one proven component beside a hybrid;
        # the Strategy Generator publishes only the composed path.
        if selected_grid is not None and (selected_hybrid is None or selected_nom is None):
            retained_windows.append(selected_grid)
        return DailyReferenceChargeWindowSet(
            window_set_id=charge_windows.window_set_id,
            snapshot_id=charge_windows.snapshot_id,
            windows=tuple(retained_windows),
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
            discovery_status="discovered",
            hybrid_schedules=((selected_hybrid,) if selected_hybrid is not None else ()),
        )

    @staticmethod
    def _preserve_pv_around_grid_charge(
        schedule: DailyReferenceIntentSchedule,
    ) -> DailyReferenceIntentSchedule:
        """Keep PV capture admissible before and after residual grid charging.

        The physical discoverer has already bounded the grid duration.  This
        user-rule projection changes no grid energy; it only prevents a
        household-discharge gap between the PV-capture path and that grid
        block, and restores NOM for one interval afterwards.  That gives live
        PV which exceeds the forecast an immediate storage path without
        creating another combinatorial timing search.
        """

        grid_indexes = tuple(
            index
            for index, interval in enumerate(schedule.intervals)
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        )
        if not grid_indexes:
            return schedule
        first_grid = grid_indexes[0]
        last_grid = grid_indexes[-1]
        existing_nom = tuple(
            index
            for index, interval in enumerate(schedule.intervals)
            if interval.intent is DailyStorageIntent.NOM
        )
        capture_start = min(existing_nom, default=max(first_grid - 1, 0))
        # The discoverer already bounded NOM to the complete Solcast surplus
        # projection. Preserve that full window; the residual grid block is an
        # overlay, not a reason to return to household support early.
        capture_end = max(
            max(existing_nom, default=0),
            min(last_grid + 1, len(schedule.intervals) - 1),
        )
        intervals = tuple(
            replace(interval, intent=DailyStorageIntent.NOM)
            if capture_start <= index <= capture_end
            and interval.intent is not DailyStorageIntent.GRID_REQUIREMENT
            else interval
            for index, interval in enumerate(schedule.intervals)
        )
        return replace(
            schedule,
            schedule_id=f"{schedule.schedule_id}:preserve-pv",
            intervals=intervals,
        )

    @staticmethod
    def _pv_capture_schedule(
        *,
        snapshot_id: str,
        household: DomainHouseholdForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
    ) -> DailyReferenceIntentSchedule | None:
        """Publish one physical NOM path exactly where conservative PV exists."""

        conservative = next(item for item in pv_scenarios if item.scenario is PVScenario.LOWER)
        intervals = tuple(
            DailyReferenceIntentInterval(
                starts_at=load.starts_at,
                ends_at=load.ends_at,
                intent=(
                    DailyStorageIntent.NOM
                    if pv.energy_wh > 1e-6
                    else DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
                ),
            )
            for load, pv in zip(
                household.intervals,
                conservative.timeline.intervals,
                strict=True,
            )
        )
        if not any(item.intent is DailyStorageIntent.NOM for item in intervals):
            return None
        return DailyReferenceIntentSchedule(
            schedule_id=f"daily-strategy:{snapshot_id}:conservative-pv-capture",
            snapshot_id=snapshot_id,
            horizon_start=household.horizon_start,
            horizon_end=household.horizon_end,
            intervals=intervals,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _grid_start(schedule: DailyReferenceIntentSchedule) -> datetime:
        return next(
            item.starts_at
            for item in schedule.intervals
            if item.intent is DailyStorageIntent.GRID_REQUIREMENT
        )

    @staticmethod
    def _starts_in_preferred_window(
        starts_at: datetime,
        windows: tuple[tuple[datetime, datetime], ...],
    ) -> bool:
        return any(start <= starts_at < end for start, end in windows)

    @staticmethod
    def _grid_schedule_cost(
        schedule: DailyReferenceIntentSchedule,
        tariffs: DailyReferenceTariffSchedule,
    ) -> float:
        total_eur_per_kw = 0.0
        for planned in schedule.intervals:
            if planned.intent is not DailyStorageIntent.GRID_REQUIREMENT:
                continue
            for tariff in tariffs.intervals:
                overlap_start = max(planned.starts_at, tariff.starts_at)
                overlap_end = min(planned.ends_at, tariff.ends_at)
                if overlap_end <= overlap_start:
                    continue
                total_eur_per_kw += (
                    (overlap_end - overlap_start).total_seconds()
                    / 3600.0
                    * tariff.import_eur_per_kwh
                )
        return total_eur_per_kw

    @staticmethod
    def _nom_schedule_cost(
        schedule: DailyReferenceIntentSchedule,
        tariffs: DailyReferenceTariffSchedule,
    ) -> float:
        """Value the PV retained by NOM at its foregone export tariff."""

        total_eur_per_kw = 0.0
        for planned in schedule.intervals:
            if planned.intent is not DailyStorageIntent.NOM:
                continue
            for tariff in tariffs.intervals:
                overlap_start = max(planned.starts_at, tariff.starts_at)
                overlap_end = min(planned.ends_at, tariff.ends_at)
                if overlap_end <= overlap_start:
                    continue
                total_eur_per_kw += (
                    (overlap_end - overlap_start).total_seconds()
                    / 3600.0
                    * tariff.export_eur_per_kwh
                )
        return total_eur_per_kw

    def build_inputs(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        horizon_end: datetime | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
        extra_boundaries: tuple[datetime, ...] = (),
    ) -> _DailyReferenceInputs:
        """Expose the validated simulator inputs to composition-only planners."""

        return self._inputs(
            snapshot,
            horizon_end=horizon_end,
            maximum_duration=maximum_duration,
            extra_boundaries=extra_boundaries,
        )

    def _inputs(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        horizon_end: datetime | None = None,
        maximum_duration: timedelta = DAILY_REFERENCE_DURATION,
        extra_boundaries: tuple[datetime, ...] = (),
    ) -> _DailyReferenceInputs:
        if snapshot.horizon_end is None:
            raise DailyReferenceInputError("daily_reference_horizon_missing")
        if snapshot.household_load_forecast is None:
            raise DailyReferenceInputError("daily_reference_household_missing")
        if snapshot.pv_energy_timeline is None:
            raise DailyReferenceInputError("daily_reference_pv_missing")
        if len(snapshot.current_storage_states) != 1:
            raise DailyReferenceInputError("daily_reference_storage_scope_ambiguous")
        storage = snapshot.current_storage_states[0]
        capability_set = snapshot.capability_snapshot_set
        if capability_set is None:
            raise DailyReferenceInputError("daily_reference_capability_missing")
        if (
            capability_set.snapshot_id != snapshot.snapshot_id
            or capability_set.captured_at != snapshot.captured_at
        ):
            raise DailyReferenceInputError("daily_reference_capability_lineage_mismatch")
        capabilities = tuple(
            item
            for item in capability_set.capabilities
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(capabilities) != 1:
            raise DailyReferenceInputError("daily_reference_capability_ambiguous")
        capability = capabilities[0]
        if (
            capability.availability is not CapabilityAvailability.AVAILABLE
            or capability.health is not CapabilityHealth.HEALTHY
        ):
            raise DailyReferenceInputError("daily_reference_capability_unavailable")
        directions = set(capability.flow_directions)
        if EnergyFlowDirection.BIDIRECTIONAL not in directions and not {
            EnergyFlowDirection.CHARGE,
            EnergyFlowDirection.DISCHARGE,
        }.issubset(directions):
            raise DailyReferenceInputError("daily_reference_directions_incomplete")
        physical_limits = tuple(
            item
            for item in snapshot.storage_physical_limits
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(physical_limits) != 1:
            raise DailyReferenceInputError("daily_reference_physical_limits_missing")
        limits = physical_limits[0]
        maximum_reference_horizon_end = snapshot.captured_at + maximum_duration
        reference_horizon_end = horizon_end or maximum_reference_horizon_end
        if snapshot.horizon_end < reference_horizon_end:
            raise DailyReferenceInputError("daily_reference_horizon_too_short")
        if (
            reference_horizon_end <= snapshot.captured_at
            or reference_horizon_end > maximum_reference_horizon_end
        ):
            raise DailyReferenceInputError("daily_reference_horizon_invalid")

        household = self._household(
            snapshot.household_load_forecast,
            captured_at=snapshot.captured_at,
            horizon_end=reference_horizon_end,
            extra_boundaries=extra_boundaries
            + tuple(
                boundary
                for plan in (
                    snapshot.daily_charge_context.main_plans
                    if snapshot.daily_charge_context
                    else ()
                )
                if snapshot.daily_charge_context is not None
                and snapshot.daily_charge_context.market_plan_bindings
                and plan.plan_id in snapshot.daily_charge_context.active_main_plan_ids
                for segment in plan.segments
                for boundary in (segment.starts_at, segment.ends_at)
            ),
        )
        pv_scenarios = self._pv_scenarios(
            snapshot.pv_energy_timeline,
            household=household,
            captured_at=snapshot.captured_at,
        )
        domain_storage = DomainStorageState(
            storage_state_id=storage.storage_state_id,
            execution_scope_id=storage.execution_scope_id,
            capability_id=storage.capability_id,
            current_soc=storage.current_soc,
            usable_capacity_wh=storage.usable_capacity_wh,
            measured_at=storage.measured_at,
            confidence=storage.confidence,
            evidence_ids=storage.evidence_ids,
        )
        return _DailyReferenceInputs(
            household=household,
            pv_scenarios=pv_scenarios,
            storage=domain_storage,
            minimum_storage_energy_wh=(limits.minimum_soc * storage.usable_capacity_wh),
            target_storage_energy_wh=(limits.maximum_soc * storage.usable_capacity_wh),
            maximum_charge_input_power_w=(limits.maximum_charge_input_power_w),
            maximum_discharge_output_power_w=(limits.maximum_discharge_output_power_w),
        )

    @staticmethod
    def _validate_tariffs(
        snapshot: PlanningInputSnapshot,
        household: DomainHouseholdForecast,
        tariffs: DailyReferenceTariffSchedule,
    ) -> None:
        if tariffs.snapshot_id != snapshot.snapshot_id:
            raise DailyReferenceInputError("daily_reference_tariff_lineage_mismatch")
        if (
            tariffs.horizon_start != household.horizon_start
            or tariffs.horizon_end != household.horizon_end
        ):
            raise DailyReferenceInputError("daily_reference_tariff_horizon_mismatch")

    @staticmethod
    def _household(
        forecast: HouseholdLoadForecast,
        *,
        captured_at: datetime,
        horizon_end: datetime,
        extra_boundaries: tuple[datetime, ...] = (),
    ) -> DomainHouseholdForecast:
        source_intervals = tuple(
            interval
            for interval in forecast.intervals
            if interval.starts_at < horizon_end and interval.ends_at > captured_at
        )
        if not source_intervals:
            raise DailyReferenceInputError("daily_reference_household_empty")
        boundaries = [captured_at]
        next_quarter = captured_at.replace(second=0, microsecond=0)
        remainder = next_quarter.minute % 15
        if remainder:
            next_quarter += timedelta(minutes=15 - remainder)
        elif next_quarter < captured_at:
            next_quarter += timedelta(minutes=15)
        if captured_at < next_quarter < horizon_end:
            boundaries.append(next_quarter)
        while boundaries[-1] + timedelta(minutes=15) < horizon_end:
            boundaries.append(boundaries[-1] + timedelta(minutes=15))
        if boundaries[-1] != horizon_end:
            boundaries.append(horizon_end)
        boundaries = sorted(set(boundaries) | {
            t for t in extra_boundaries if captured_at < t < horizon_end
        })

        normalised: list[DomainHouseholdInterval] = []
        for starts_at, ends_at in zip(boundaries, boundaries[1:], strict=False):
            overlapping = tuple(
                item
                for item in source_intervals
                if item.starts_at < ends_at and item.ends_at > starts_at
            )
            covered_seconds = sum(
                (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
                for item in overlapping
            )
            required_seconds = (ends_at - starts_at).total_seconds()
            if not overlapping or covered_seconds != required_seconds:
                raise DailyReferenceInputError("daily_reference_household_horizon_incomplete")
            expected_energy_wh = sum(
                item.expected_energy_wh
                * (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
                / (item.ends_at - item.starts_at).total_seconds()
                for item in overlapping
            )
            normalised.append(
                DomainHouseholdInterval(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    expected_energy_wh=expected_energy_wh,
                    confidence=min(item.confidence for item in overlapping),
                )
            )
        return DomainHouseholdForecast(
            forecast_id=forecast.forecast_id,
            created_at=captured_at,
            horizon_start=captured_at,
            horizon_end=horizon_end,
            intervals=tuple(normalised),
            historical_source_reference=forecast.forecast_id,
            method_version=METHOD_VERSION,
        )

    def _pv_scenarios(
        self,
        timeline: PVEnergyTimeline,
        *,
        household: DomainHouseholdForecast,
        captured_at: datetime,
    ) -> tuple[ScenarioTimeline, ...]:
        return tuple(
            ScenarioTimeline(
                scenario=scenario,
                timeline=DomainPVTimeline(
                    timeline_id=f"{timeline.timeline_id}:{scenario.value}",
                    created_at=captured_at,
                    horizon_start=household.horizon_start,
                    horizon_end=household.horizon_end,
                    intervals=tuple(
                        self._normalise_pv_interval(
                            target.starts_at,
                            target.ends_at,
                            timeline.intervals,
                            scenario,
                        )
                        for target in household.intervals
                    ),
                ),
            )
            for scenario in PVScenario
        )

    @staticmethod
    def _normalise_pv_interval(
        starts_at: datetime,
        ends_at: datetime,
        source_intervals: tuple[PVEnergyTimelineInterval, ...],
        scenario: PVScenario,
    ) -> DomainPVInterval:
        overlapping = tuple(
            item
            for item in source_intervals
            if item.starts_at < ends_at and item.ends_at > starts_at
        )
        if not overlapping:
            raise DailyReferenceInputError("daily_reference_pv_gap")
        if any(item.forecast_range_status != "available" for item in overlapping):
            raise DailyReferenceInputError("daily_reference_pv_range_incomplete")
        covered_seconds = sum(
            (min(item.ends_at, ends_at) - max(item.starts_at, starts_at)).total_seconds()
            for item in overlapping
        )
        required_seconds = (ends_at - starts_at).total_seconds()
        if covered_seconds != required_seconds:
            raise DailyReferenceInputError("daily_reference_pv_coverage_incomplete")

        energy_wh = 0.0
        evidence_ids: list[str] = []
        confidence = 1.0
        for item in overlapping:
            values = {
                PVScenario.LOWER: item.forecast_lower_energy_wh,
                PVScenario.CENTRAL: item.forecast_central_energy_wh,
                PVScenario.UPPER: item.forecast_upper_energy_wh,
            }
            source_energy_wh = values[scenario]
            if source_energy_wh is None:
                raise DailyReferenceInputError("daily_reference_pv_range_incomplete")
            overlap_seconds = (
                min(item.ends_at, ends_at) - max(item.starts_at, starts_at)
            ).total_seconds()
            source_seconds = (item.ends_at - item.starts_at).total_seconds()
            energy_wh += source_energy_wh * overlap_seconds / source_seconds
            evidence_ids.extend((item.interval_id, *item.forecast_evidence_ids))
            confidence = min(confidence, item.confidence)
        return DomainPVInterval(
            starts_at=starts_at,
            ends_at=ends_at,
            energy_wh=energy_wh,
            evidence_type=PVEnergyEvidenceType.FORECAST,
            confidence=confidence,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            method_version=METHOD_VERSION,
        )
