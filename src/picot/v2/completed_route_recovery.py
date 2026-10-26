"""Canonical remainder candidates for a proven completed day without a next session."""

from datetime import timedelta

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
)
from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.energy_path import EnergyPath, PathSegment, ProjectedEnergyState, SocConstraint
from picot.domain.evaluation import CandidateOutcome, CandidateOutcomeSet, CandidateValidity
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.mep_candidate_outcomes import (
    MainChargeComparablePortfolio,
    _main_charge_segment_invalidity,
    _strategy,
)
from picot.v2.completed_route_history import is_reset_household_route, passive_remainder_available
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.market_rule_planning import identity


def historical_reference(
    snapshot: PlanningInputSnapshot,
    owner: DailyChargeAssignment,
    plan: ExecutionPlan | None,
) -> ExecutionPlan | None:
    context = snapshot.daily_charge_context
    if context is None:
        return None
    if plan is not None and (
        plan.plan_id not in context.completed_route_plan_ids or not is_reset_household_route(plan)
    ):
        return None
    archived = next((p for p in context.main_plans if p.plan_id == owner.route_plan_id), None)
    if archived is not None and passive_remainder_available(archived, owner, snapshot.captured_at):
        return archived
    return None


def recovery_owner(
    snapshot: PlanningInputSnapshot, plan: ExecutionPlan | None
) -> DailyChargeAssignment | None:
    context = snapshot.daily_charge_context
    if context is None or context.status != "ready" or len(snapshot.current_storage_states) != 1:
        return None
    scope = snapshot.current_storage_states[0].execution_scope_id
    owners = [a for a in context.assignments if a.execution_scope_id == scope]
    if any(a.completed_at is None and a.ends_at > snapshot.captured_at for a in owners):
        return None  # The existing main/bridge pipeline owns pending daily obligations.
    completed = [
        a
        for a in owners
        if a.completed_at is not None and a.starts_at <= snapshot.captured_at < a.ends_at
    ]
    if not completed:
        return None
    owner = max(completed, key=lambda a: a.delivery_date)
    if (
        plan is not None
        and historical_reference(snapshot, owner, plan) is None
        and not any(
            s.main_assignment_id == owner.assignment_id and s.ends_at > snapshot.captured_at
            for s in plan.segments
        )
    ):
        return None
    return owner


def portfolio(
    snapshot: PlanningInputSnapshot,
    owner: DailyChargeAssignment,
    plan: ExecutionPlan | None,
    conversion: StorageConversionModel,
    opportunity_ids: tuple[str, ...],
) -> MainChargeComparablePortfolio:
    """Validate one corrective path; no price optimisation or new daily obligation."""
    context = snapshot.daily_charge_context
    if context is None or snapshot.capability_snapshot_set is None:
        raise ValueError("completed_route_capabilities_unavailable")
    if recovery_owner(snapshot, plan) != owner:
        raise ValueError("completed_route_requires_current_completed_owner")
    reference = historical_reference(snapshot, owner, plan)
    if reference is not None:
        plan = reference
    adapter = IndependentDailyReferenceAdapter()
    end = (
        min(reference.valid_until, owner.ends_at)
        if reference is not None
        else plan.valid_until
        if plan is not None
        else owner.ends_at
    )
    tariffs = IndependentDailyTariffAdapter()
    tariffs.build(snapshot, horizon_end=end)  # Missing prices never become invented coverage.
    data = adapter._inputs(
        snapshot,
        horizon_end=end,
        maximum_duration=timedelta(hours=49),
        extra_boundaries=tuple(t for s in plan.segments for t in (s.starts_at, s.ends_at))
        if plan
        else (),
    )
    released = adapter._released_grid_intents(data)
    cid = identity("completed-route-continuity" if reference else "completed-route",
                   snapshot.snapshot_id + owner.assignment_id)
    limits = next(
        limit
        for limit in snapshot.storage_physical_limits
        if limit.execution_scope_id == owner.execution_scope_id
    )
    parts: list[PathSegment] = []
    intervals = []
    intents = {
        Primitive.BALANCE_DISCHARGE_ONLY: Intent.HOUSEHOLD_SUPPORT_ONLY,
        Primitive.BALANCE_BIDIRECTIONAL: Intent.NOM,
        Primitive.STANDBY: Intent.STANDBY,
        Primitive.CHARGE_AT_POWER: Intent.GRID_REQUIREMENT,
        Primitive.DISCHARGE_AT_POWER: Intent.STORAGE_EXPORT,
    }
    for i in data.household.intervals:
        old = (
            next(
                (s for s in plan.segments if s.starts_at <= i.starts_at < i.ends_at <= s.ends_at),
                None,
            )
            if plan
            else None
        )
        if plan is not None and old is None:
            raise ValueError("completed_route_has_schedule_gap")
        changed = old is None or old.main_assignment_id == owner.assignment_id
        intent = (
            released[(i.starts_at, i.ends_at)] if changed or old is None else intents[old.primitive]
        )
        export = 0.0
        if intent is Intent.STORAGE_EXPORT:
            assert old is not None
            binding = next(
                b for b in context.market_plan_bindings if old.segment_id in b.segment_ids
            )
            export = binding.segment_export_wh[binding.segment_ids.index(old.segment_id)] * (
                (i.ends_at - i.starts_at).total_seconds()
                / (old.ends_at - old.starts_at).total_seconds()
            )
        intervals.append(DailyReferenceIntentInterval(i.starts_at, i.ends_at, intent, export))
        primitive = (
            (
                Primitive.BALANCE_BIDIRECTIONAL
                if intent is Intent.NOM
                else Primitive.BALANCE_DISCHARGE_ONLY
            )
            if changed or old is None
            else old.primitive
        )
        parts.append(
            PathSegment(
                identity("completed-part", cid + str(i.starts_at)),
                len(parts) + 1,
                owner.execution_scope_id,
                i.starts_at,
                i.ends_at,
                primitive,
                snapshot.current_storage_states[0].capability_id
                if old is None
                else old.capability_id,
                "completed-day-household" if changed or old is None else old.purpose,
                (owner.completion_evidence_id or owner.assignment_id,),
                requested_power_w=None if changed or old is None else old.requested_power_w,
                soc_constraint=SocConstraint(limits.minimum_soc, limits.maximum_soc)
                if old is None
                else old.soc_constraint,
                energy_profile_id=None if changed or old is None else old.energy_profile_id,
                charge_source_policy=(
                    ChargeSourcePolicy.PV_ONLY
                    if primitive is Primitive.BALANCE_BIDIRECTIONAL
                    else None
                )
                if changed or old is None
                else old.charge_source_policy,
                main_assignment_id=None if changed or old is None else old.main_assignment_id,
                retained_execution_origin=None
                if changed or old is None
                else old.retained_execution_origin,
            )
        )
    schedule = DailyReferenceIntentSchedule(
        cid, snapshot.snapshot_id, snapshot.captured_at, end, tuple(intervals), "completed-route:v1"
    )
    projection = adapter._bridge_projection(snapshot, data, schedule, conversion)
    storage = snapshot.current_storage_states[0]
    limits = next(
        limit
        for limit in snapshot.storage_physical_limits
        if limit.execution_scope_id == owner.execution_scope_id
    )
    capability = next(
        c
        for c in snapshot.capability_snapshot_set.capabilities
        if c.capability_id == storage.capability_id
    )
    invalid = list(
        _main_charge_segment_invalidity(tuple(parts), capability, limits, incumbent=True)
    )
    if any(
        min(i.storage_energy_at_start_wh, i.storage_energy_at_end_wh) + 1e-6
        < data.minimum_storage_energy_wh
        for i in projection.intervals
    ):
        invalid.append("household_reserve_unreachable")
    if not adapter._retirement_exports_valid(schedule, projection):
        invalid.append("completed_route_export_unreachable")
    for goal in context.supplemental_assignments:
        if (
            goal.completed_at is None
            and goal.ends_at > snapshot.captured_at
            and not any(
                goal.starts_at <= i.ends_at <= goal.ends_at
                and i.storage_energy_at_end_wh + 1e-6
                >= goal.target_soc * storage.usable_capacity_wh
                for i in projection.intervals
            )
        ):
            invalid.append("supplemental_goal_unreachable:" + goal.assignment_id)
    for scope, at, energy in snapshot.storage_reserve_checkpoints:
        if (
            scope == owner.execution_scope_id
            and at > snapshot.captured_at
            and not any(
                i.ends_at == at and i.storage_energy_at_end_wh + 1e-6 >= energy
                for i in projection.intervals
            )
        ):
            invalid.append("promised_storage_reserve_unreachable")
    confidence = min(i.confidence for i in projection.intervals)
    strategy = _strategy(snapshot)
    path = EnergyPath(
        identity("completed-path", cid),
        snapshot.snapshot_id,
        CandidateFamily.PRIORITY_FIRST,
        snapshot.captured_at,
        end,
        tuple(parts),
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
        plan.mapping_version if plan else snapshot.capability_snapshot_set.mapping_version,
        ("Completed daily goal remains completed; no invented next charge session.",),
        confidence,
    )
    candidate = Candidate(
        cid,
        snapshot.snapshot_id,
        path.family,
        path.path_id,
        opportunity_ids,
        (),
        path.strategy_version,
        path.capability_ids,
        path.assumptions,
        confidence,
    )
    candidates = CandidateSet(
        snapshot.snapshot_id, strategy.strategy_version, (candidate,), (path,), ()
    )
    outcome = CandidateOutcome(
        cid,
        (),
        confidence,
        None,
        len(parts),
        max(0, len(parts) - 1),
        "completed-route:v1",
        CandidateValidity.INVALID if invalid else CandidateValidity.VALID,
        invalidity_reasons=tuple(invalid),
        evidence_ids=(owner.completion_evidence_id or owner.assignment_id,),
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
