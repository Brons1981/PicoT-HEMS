"""Candidate construction for the one-time, unstarted morning-route transition."""

from dataclasses import replace
from datetime import timedelta

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.energy_path import (
    EnergyPath,
    PathSegment,
    ProjectedEnergyState,
    RetainedExecutionOrigin,
)
from picot.domain.evaluation import CandidateOutcome, CandidateOutcomeSet, CandidateValidity
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.mep_candidate_outcomes import (
    MainChargeComparablePortfolio,
    _main_charge_segment_invalidity,
    _strategy,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.market_rule_planning import identity


def transition_portfolio(
    *,
    snapshot: PlanningInputSnapshot,
    plan: ExecutionPlan,
    binding: MarketPlanBinding,
    conversion: StorageConversionModel,
    opportunity_ids: tuple[str, ...],
) -> MainChargeComparablePortfolio:
    """Remove only the specified export; simulate all unchanged charging obligations."""
    context = snapshot.daily_charge_context
    assert context is not None and snapshot.capability_snapshot_set is not None
    owner = next(
        a
        for a in context.assignments
        if a.route_plan_id is not None and a.execution_scope_id == plan.execution_scope_id
    )
    adapter = IndependentDailyReferenceAdapter()
    data = adapter.build_inputs(
        snapshot, horizon_end=plan.valid_until, maximum_duration=timedelta(hours=49)
    )
    schedule, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=data, supplied=None
    )
    assert schedule is not None
    parts = tuple(s for s in plan.segments if s.purpose == binding.assignment_id)
    schedule = replace(
        schedule,
        schedule_id=identity("market-window-release", snapshot.snapshot_id),
        intervals=tuple(
            replace(i, intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY, storage_export_target_wh=0)
            if any(s.starts_at <= i.starts_at < i.ends_at <= s.ends_at for s in parts)
            else i
            for i in schedule.intervals
        ),
    )
    projection = adapter._bridge_projection(snapshot, data, schedule, conversion)
    storage = snapshot.current_storage_states[0]
    limits = next(
        limit
        for limit in snapshot.storage_physical_limits
        if limit.execution_scope_id == plan.execution_scope_id
    )
    capability = next(
        c
        for c in snapshot.capability_snapshot_set.capabilities
        if c.capability_id == storage.capability_id
    )
    segments = tuple(
        PathSegment(
            identity("market-release-segment", f"{schedule.schedule_id}|{s.segment_id}"),
            n + 1,
            plan.execution_scope_id,
            s.starts_at,
            s.ends_at,
            ExecutionPrimitive.BALANCE_DISCHARGE_ONLY if s in parts else s.primitive,
            s.capability_id,
            "household-support" if s in parts else s.purpose,
            (binding.assignment_id, schedule.schedule_id),
            requested_power_w=None if s in parts else s.requested_power_w,
            soc_constraint=s.soc_constraint,
            energy_profile_id=None if s in parts else s.energy_profile_id,
            charge_source_policy=None if s in parts else s.charge_source_policy,
            main_assignment_id=s.main_assignment_id,
            retained_execution_origin=s.retained_execution_origin
            or (
                RetainedExecutionOrigin(plan.plan_id, s.segment_id)
                if s.main_assignment_id
                else None
            ),
        )
        for n, s in enumerate(plan.segments)
    )
    invalid = list(_main_charge_segment_invalidity(segments, capability, limits, incumbent=True))
    if any(
        min(i.storage_energy_at_start_wh, i.storage_energy_at_end_wh) + 1e-6
        < data.minimum_storage_energy_wh
        for i in projection.intervals
    ):
        invalid.append("household_reserve_unreachable")
    for a in context.assignments:
        if a.completed_at is not None or a.ends_at <= snapshot.captured_at or not a.main_segments:
            continue
        if not any(
            energy + 1e-6 >= storage.usable_capacity_wh
            and any(s.starts_at <= at <= s.ends_at for s in a.main_segments)
            for i in projection.intervals
            for at, energy in (
                (i.starts_at, i.storage_energy_at_start_wh),
                (i.ends_at, i.storage_energy_at_end_wh),
            )
        ):
            invalid.append(f"daily_main_goal_unreachable:{a.assignment_id}")
    for goal in context.supplemental_assignments:
        if (
            goal.completed_at is None
            and goal.ends_at > snapshot.captured_at
            and not any(
                i.ends_at == goal.ends_at
                and i.storage_energy_at_end_wh + 1e-6
                >= goal.target_soc * storage.usable_capacity_wh
                for i in projection.intervals
            )
        ):
            invalid.append(f"supplemental_goal_unreachable:{goal.assignment_id}")
    confidence = min(i.confidence for i in projection.intervals)
    strategy = _strategy(snapshot)
    candidate_id = identity("market-window-release", snapshot.snapshot_id + binding.assignment_id)
    path = EnergyPath(
        identity("market-window-release-path", candidate_id),
        snapshot.snapshot_id,
        CandidateFamily.MARKET_ROUTE,
        plan.valid_from,
        plan.valid_until,
        segments,
        (
            ProjectedEnergyState(
                at=snapshot.captured_at,
                confidence=confidence,
                storage_energy_wh=storage.current_stored_energy_wh,
                battery_soc=storage.current_soc,
            ),
        )
        + tuple(
            ProjectedEnergyState(
                at=i.ends_at,
                confidence=i.confidence,
                storage_energy_wh=i.storage_energy_at_end_wh,
                battery_soc=min(1, i.storage_energy_at_end_wh / storage.usable_capacity_wh),
            )
            for i in projection.intervals
        ),
        opportunity_ids,
        (),
        (storage.capability_id,),
        strategy.strategy_version,
        plan.mapping_version,
        ("ADR-019.7: release unstarted morning export; retain charge instructions",),
        confidence,
    )
    candidate = Candidate(
        candidate_id,
        snapshot.snapshot_id,
        path.family,
        path.path_id,
        opportunity_ids,
        path.constraint_ids,
        path.strategy_version,
        path.capability_ids,
        path.assumptions,
        confidence,
    )
    candidates = CandidateSet(
        snapshot.snapshot_id, strategy.strategy_version, (candidate,), (path,), ()
    )
    outcome = CandidateOutcome(
        candidate_id,
        (),
        confidence,
        None,
        len(segments),
        max(0, len(segments) - 1),
        "market-window-transition:v1",
        CandidateValidity.INVALID if invalid else CandidateValidity.VALID,
        invalidity_reasons=tuple(invalid),
        evidence_ids=(binding.assignment_id,),
    )
    return MainChargeComparablePortfolio(
        candidates,
        CandidateOutcomeSet(
            snapshot.snapshot_id,
            strategy.strategy_version,
            EvaluationEngine.candidate_set_reference(candidates),
            (outcome,),
        ),
        strategy,
        (),
    )
