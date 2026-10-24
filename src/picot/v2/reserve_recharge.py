"""Generic reserve acquisition; no daily goal is reopened or inferred."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
)
from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.daily_reference_simulation import DailyPlanningProjection
from picot.domain.energy_path import (
    EnergyPath,
    PathSegment,
    ProjectedEnergyState,
    RetainedExecutionOrigin,
)
from picot.domain.evaluation import CandidateOutcome, CandidateOutcomeSet, CandidateValidity
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement
from picot.planner.mep_candidate_outcomes import (
    MainChargeComparablePortfolio,
    _main_charge_segment_invalidity,
    _objective_outcomes,
    _strategy,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_bridge import energy_deficits
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.market_rule_planning import identity


@dataclass(frozen=True)
class ReserveWindow:
    schedule: DailyReferenceIntentSchedule
    projection: DailyPlanningProjection


@dataclass(frozen=True)
class ReservePortfolio:
    comparable: MainChargeComparablePortfolio
    windows: dict[str, ReserveWindow]


def requirements(
    snapshot: PlanningInputSnapshot, scope: str,
) -> tuple[tuple[str, datetime, float], ...]:
    grouped: dict[datetime, float] = {}
    for candidate_scope, at, energy in snapshot.storage_reserve_checkpoints:
        if candidate_scope == scope and at > snapshot.captured_at:
            grouped[at] = max(grouped.get(at, 0), energy)
    return tuple((scope, at, energy) for at, energy in sorted(grouped.items()))


def portfolio(
    snapshot: PlanningInputSnapshot,
    plan: ExecutionPlan,
    conversion: StorageConversionModel,
    opportunity_ids: tuple[str, ...] = (),
) -> ReservePortfolio | None:
    checkpoints = tuple((at, wh) for _, at, wh in requirements(snapshot, plan.execution_scope_id))
    if not checkpoints or snapshot.external_load_policy is not None:
        return None
    if any(at > plan.valid_until for at, _ in checkpoints):
        raise ValueError("reserve_checkpoint_outside_committed_horizon")
    context = snapshot.daily_charge_context
    capabilities = snapshot.capability_snapshot_set
    if context is None or capabilities is None:
        raise ValueError("reserve_acquisition_context_missing")
    adapter = IndependentDailyReferenceAdapter()
    data = adapter._inputs(
        snapshot,
        horizon_end=plan.valid_until,
        maximum_duration=timedelta(hours=49),
        extra_boundaries=tuple(t for s in plan.segments for t in (s.starts_at, s.ends_at)),
    )
    baseline, schedule = adapter.committed_plan_projection(
        snapshot=snapshot,
        plan=plan,
        conversion_model=conversion,
    )

    def satisfied(projection: DailyPlanningProjection) -> bool:
        return all(
            any(
                i.ends_at == at and i.storage_energy_at_end_wh + 1e-6 >= wh
                for i in projection.intervals
            )
            for at, wh in checkpoints
        )

    if satisfied(baseline):
        return None
    # Existing acquisitions, including a running charge, are immutable here.
    free = tuple(
        n
        for n, i in enumerate(schedule.intervals)
        if i.ends_at <= max(at for at, _ in checkpoints)
        and any(
            s.starts_at <= i.starts_at < i.ends_at <= s.ends_at
            and s.main_assignment_id is None
            and not s.purpose.startswith(("supplemental:", "reserve:"))
            and s.primitive
            in (
                Primitive.BALANCE_DISCHARGE_ONLY,
                Primitive.BALANCE_BIDIRECTIONAL,
                Primitive.STANDBY,
            )
            for s in plan.segments
        )
    )
    projections: dict[tuple[DailyReferenceIntentInterval, ...], DailyPlanningProjection] = {}
    schedules: dict[tuple[DailyReferenceIntentInterval, ...], DailyReferenceIntentSchedule] = {}

    def project(intervals: tuple[DailyReferenceIntentInterval, ...]) -> DailyPlanningProjection:
        if intervals not in projections:
            candidate = replace(
                schedule,
                schedule_id=identity("reserve", snapshot.snapshot_id + repr(intervals)),
                intervals=intervals,
            )
            projections[intervals] = adapter._bridge_projection(
                snapshot, data, candidate, conversion
            )
            schedules[intervals] = candidate
        return projections[intervals]

    pv = tuple(
        replace(i, intent=Intent.NOM)
        if n in free
        and baseline.intervals[n].usable_pv_wh > baseline.intervals[n].household_demand_wh
        else i
        for n, i in enumerate(schedule.intervals)
    )
    attempts = {pv}
    for seed in dict.fromkeys((schedule.intervals, pv)):
        for index, _start in enumerate(free):
            consecutive: list[int] = []
            for end in free[index:]:
                if consecutive and end != consecutive[-1] + 1:
                    break
                consecutive.append(end)
            low, high = 1, len(consecutive)
            while low < high:
                mid = (low + high) // 2
                trial = tuple(
                    replace(i, intent=Intent.GRID_REQUIREMENT) if n in consecutive[:mid] else i
                    for n, i in enumerate(seed)
                )
                if satisfied(project(trial)):
                    high = mid
                else:
                    low = mid + 1
            attempts.add(
                tuple(
                    replace(i, intent=Intent.GRID_REQUIREMENT) if n in consecutive[:low] else i
                    for n, i in enumerate(seed)
                )
            )
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=plan.valid_until)
    settlement = IndependentDailyFinancialSettlement()
    storage = snapshot.current_storage_states[0]
    limits = next(
        i
        for i in snapshot.storage_physical_limits
        if i.execution_scope_id == plan.execution_scope_id
    )
    capability = next(
        c
        for c in capabilities.capabilities
        if c.capability_id == storage.capability_id
    )
    strategy = _strategy(snapshot)
    candidates, paths, outcomes, windows = [], [], [], {}
    for intervals in sorted(attempts, key=repr):
        projection = project(intervals)
        candidate_schedule = schedules[intervals]
        if (
            not satisfied(projection)
            or not adapter._retirement_exports_valid(candidate_schedule, projection)
            or any(
                i.deficit_wh > 1e-6
                for i in energy_deficits(
                    projection,
                    candidate_schedule,
                    until=plan.valid_until,
                    maximum_discharge_output_power_w=limits.maximum_discharge_output_power_w,
                )
            )
        ):
            continue
        if any(
            not any(
                energy + 1e-6 >= storage.usable_capacity_wh
                and any(m.starts_at <= at <= m.ends_at for m in a.main_segments)
                for i in projection.intervals
                for at, energy in (
                    (i.starts_at, i.storage_energy_at_start_wh),
                    (i.ends_at, i.storage_energy_at_end_wh),
                )
            )
            for a in context.assignments
            if a.completed_at is None and a.main_segments and a.ends_at > snapshot.captured_at
        ):
            continue
        if any(
            not any(
                g.starts_at <= i.ends_at <= g.ends_at
                and i.storage_energy_at_end_wh + 1e-6 >= g.target_soc * storage.usable_capacity_wh
                for i in projection.intervals
            )
            for g in context.supplemental_assignments
            if g.completed_at is None and g.required_by > snapshot.captured_at
        ):
            continue
        cid = candidate_schedule.schedule_id
        purpose = "reserve:" + cid
        segments: list[PathSegment] = []
        for old in plan.segments:
            edges = sorted(
                {old.starts_at, old.ends_at}
                | {
                    t
                    for i in intervals
                    for t in (i.starts_at, i.ends_at)
                    if old.starts_at < t < old.ends_at
                }
            )
            for left, right in zip(edges, edges[1:], strict=False):
                n = next(
                    (
                        n
                        for n, i in enumerate(intervals)
                        if i.starts_at <= left < right <= i.ends_at
                    ),
                    None,
                )
                changed = n is not None and intervals[n].intent != schedule.intervals[n].intent
                intent = intervals[n].intent if n is not None and changed else None
                primitive = (
                    Primitive.CHARGE_AT_POWER
                    if intent is Intent.GRID_REQUIREMENT
                    else Primitive.BALANCE_BIDIRECTIONAL
                    if changed
                    else old.primitive
                )
                segments.append(
                    PathSegment(
                        identity("reserve-part", f"{cid}|{old.segment_id}|{left}"),
                        len(segments) + 1,
                        plan.execution_scope_id,
                        left,
                        right,
                        primitive,
                        old.capability_id,
                        purpose if changed else old.purpose,
                        (cid,),
                        requested_power_w=(
                            limits.maximum_charge_input_power_w
                            if primitive is Primitive.CHARGE_AT_POWER
                            else None
                        )
                        if changed
                        else old.requested_power_w,
                        soc_constraint=old.soc_constraint,
                        energy_profile_id=old.energy_profile_id,
                        charge_source_policy=(
                            ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
                            if primitive is Primitive.CHARGE_AT_POWER
                            else ChargeSourcePolicy.PV_ONLY
                        )
                        if changed
                        else old.charge_source_policy,
                        main_assignment_id=old.main_assignment_id,
                        retained_execution_origin=old.retained_execution_origin
                        or (
                            RetainedExecutionOrigin(plan.plan_id, old.segment_id)
                            if old.main_assignment_id
                            else None
                        ),
                    )
                )
        invalid = _main_charge_segment_invalidity(
            tuple(segments), capability, limits, incumbent=True
        )
        confidence = min(i.confidence for i in projection.intervals)
        states = (
            ProjectedEnergyState(
                snapshot.captured_at, confidence, storage_energy_wh=storage.current_stored_energy_wh
            ),
        ) + tuple(
            ProjectedEnergyState(
                i.ends_at, i.confidence, storage_energy_wh=i.storage_energy_at_end_wh
            )
            for i in projection.intervals
        )
        path = EnergyPath(
            identity("reserve-path", cid),
            snapshot.snapshot_id,
            CandidateFamily.COST_FIRST,
            plan.valid_from,
            plan.valid_until,
            tuple(segments),
            states,
            opportunity_ids,
            (),
            (storage.capability_id,),
            strategy.strategy_version,
            plan.mapping_version,
            ("reserve acquisition; retain all owned actions",),
            confidence,
        )
        candidates.append(
            Candidate(
                cid,
                snapshot.snapshot_id,
                path.family,
                path.path_id,
                opportunity_ids,
                (),
                strategy.strategy_version,
                path.capability_ids,
                path.assumptions,
                confidence,
            )
        )
        paths.append(path)
        cash = settlement.settle_planning_basis(
            projection=projection, tariffs=tariffs
        ).cash_result_eur
        outcomes.append(
            CandidateOutcome(
                cid,
                _objective_outcomes(
                    financial=cash,
                    self_consumption=sum(
                        i.pv_to_household_wh + i.pv_to_storage_input_wh
                        for i in projection.intervals
                    ),
                    reserve=min(i.storage_energy_at_end_wh for i in projection.intervals),
                    confidence=confidence,
                    evidence_ids=(cid,),
                ),
                confidence,
                None,
                len(segments),
                len(segments) - 1,
                "reserve:v1",
                CandidateValidity.INVALID if invalid else CandidateValidity.VALID,
                invalidity_reasons=invalid,
                evidence_ids=(cid,),
            )
        )
        windows[cid] = ReserveWindow(candidate_schedule, projection)
    candidate_set = CandidateSet(
        snapshot.snapshot_id, strategy.strategy_version, tuple(candidates), tuple(paths), ()
    )
    return ReservePortfolio(
        MainChargeComparablePortfolio(
            candidate_set,
            CandidateOutcomeSet(
                snapshot.snapshot_id,
                strategy.strategy_version,
                EvaluationEngine.candidate_set_reference(candidate_set),
                tuple(outcomes),
            ),
            strategy,
            (),
        ),
        windows,
    )
