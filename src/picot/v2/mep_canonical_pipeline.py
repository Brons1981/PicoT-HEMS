"""Canonical stage composition for the sole Markt Etmaal Planner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import perf_counter

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_candidate import DailyReferenceCandidate
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.energy_path import PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.market_daily_evaluation_engine import MarketDailyEvaluationEngine
from picot.planner.market_daily_planner import MarketDailyPlan, MarketRouteAssessment
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    CanonicalPipelineRun,
    DeviceAdapterBoundary,
    EnergyPath,
    EvaluationRecord,
    ExecutionPlanSet,
    ExecutionPrimitiveBoundary,
    ExecutionRecord,
    ObserverExecutionPlan,
    ObserverExecutionPlanSegment,
    OpportunitySet,
    PlanningInputSnapshot,
    VendorBoundaryResult,
)
from picot.v2.market_daily_runtime import (
    MarketDailyPlannerRuntime,
    MarketDailyRuntimeOutcome,
)
from picot.v2.plan_commitment_store import (
    COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedPlanSegment,
)


@dataclass(frozen=True, slots=True)
class MepCanonicalStageTimings:
    candidate_engine_ms: float
    evaluation_engine_ms: float
    execution_plan_builder_ms: float
    execution_engine_ms: float
    execution_primitive_ms: float
    device_adapter_ms: float
    vendor_result_ms: float


def _id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _intent_primitive(
    intent: DailyStorageIntent,
) -> tuple[ExecutionPrimitive, ChargeSourcePolicy | None]:
    if intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY:
        return ExecutionPrimitive.BALANCE_DISCHARGE_ONLY, None
    if intent is DailyStorageIntent.NOM:
        return ExecutionPrimitive.BALANCE_BIDIRECTIONAL, ChargeSourcePolicy.PV_ONLY
    if intent is DailyStorageIntent.GRID_REQUIREMENT:
        return (
            ExecutionPrimitive.CHARGE_AT_POWER,
            ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED,
        )
    if intent is DailyStorageIntent.STORAGE_EXPORT:
        return ExecutionPrimitive.DISCHARGE_AT_POWER, None
    return ExecutionPrimitive.STANDBY, None


def _coalesce(
    intervals: tuple[DailyReferenceIntentInterval, ...],
) -> tuple[tuple[datetime, datetime, DailyStorageIntent], ...]:
    phases: list[tuple[datetime, datetime, DailyStorageIntent]] = []
    for interval in intervals:
        if (
            phases
            and phases[-1][1] == interval.starts_at
            and phases[-1][2] is interval.intent
        ):
            phases[-1] = (phases[-1][0], interval.ends_at, interval.intent)
        else:
            phases.append((interval.starts_at, interval.ends_at, interval.intent))
    return tuple(phases)


def _path_for_schedule(
    *,
    snapshot: PlanningInputSnapshot,
    schedule: DailyReferenceIntentSchedule,
    path_id: str,
    family: str,
    source_evidence_ids: tuple[str, ...] = (),
) -> EnergyPath:
    storage = snapshot.current_storage_states[0]
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    segments: list[PathSegment] = []
    for order, (starts_at, ends_at, intent) in enumerate(
        _coalesce(schedule.intervals),
        start=1,
    ):
        primitive, source_policy = _intent_primitive(intent)
        requested_power_w = (
            limits.maximum_charge_input_power_w
            if primitive is ExecutionPrimitive.CHARGE_AT_POWER
            else (
                limits.maximum_discharge_output_power_w
                if primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
                else None
            )
        )
        segments.append(
            PathSegment(
                segment_id=_id(
                    "mep-segment",
                    f"{schedule.schedule_id}|{starts_at.isoformat()}|{intent.value}",
                ),
                order=order,
                execution_scope_id=storage.execution_scope_id,
                starts_at=starts_at,
                ends_at=ends_at,
                primitive=primitive,
                capability_id=storage.capability_id,
                purpose=f"mep:{intent.value}",
                evidence_ids=(schedule.schedule_id, *source_evidence_ids),
                requested_power_w=requested_power_w,
                charge_source_policy=source_policy,
            )
        )
    return EnergyPath(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        path_id=path_id,
        family=family,
        segment_ids=tuple(item.segment_id for item in segments),
        segments=tuple(segments),
    )


def _native_schedules(
    plan: MarketDailyPlan,
) -> dict[str, DailyReferenceIntentSchedule]:
    return {
        item.intent_schedule.schedule_id: item.intent_schedule
        for item in plan.native_observation.observer_result.portfolio.strategy_results
    }


def _native_candidates(
    plan: MarketDailyPlan,
) -> dict[str, DailyReferenceCandidate]:
    return {
        item.candidate_id: item
        for item in plan.native_observation.observer_result.candidate_set.candidates
    }


def _selected_market_assessment(
    plan: MarketDailyPlan,
) -> MarketRouteAssessment | None:
    admitted = tuple(item for item in plan.route_assessments if item.admitted)
    return (
        max(
            admitted,
            key=lambda item: (
                item.worst_case_incremental_result_eur,
                item.minimum_incremental_result_eur_per_exported_kwh,
                item.market_schedule_id,
            ),
        )
        if admitted
        else None
    )


def _plan_candidates(
    snapshot: PlanningInputSnapshot,
    plan: MarketDailyPlan,
) -> tuple[
    list[Candidate],
    list[EnergyPath],
    str,
    DailyReferenceIntentSchedule,
    DailyReferenceCandidate | None,
    MarketRouteAssessment | None,
]:
    schedules = _native_schedules(plan)
    canonical_candidates: list[Candidate] = []
    paths: list[EnergyPath] = []
    native_by_id = _native_candidates(plan)
    for native in native_by_id.values():
        schedule = schedules[native.intent_schedule_id]
        path_id = _id("mep-energy-path", native.candidate_id)
        canonical_candidates.append(
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=native.candidate_id,
                energy_path_id=path_id,
                family=native.family.value,
                pv_forecast_basis="lower-central-upper",
            )
        )
        paths.append(
            _path_for_schedule(
                snapshot=snapshot,
                schedule=schedule,
                path_id=path_id,
                family=native.family.value,
            )
        )

    market_candidate_ids: dict[str, str] = {}
    routes_by_id = {item.route_id: item for item in plan.market_routes}
    for assessment in plan.route_assessments:
        candidate_id = _id("mep-market-candidate", assessment.market_schedule_id)
        path_id = _id("mep-energy-path", candidate_id)
        market_candidate_ids[assessment.market_schedule_id] = candidate_id
        canonical_candidates.append(
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=candidate_id,
                energy_path_id=path_id,
                family="market_route",
                pv_forecast_basis="lower-central-upper",
            )
        )
        paths.append(
            _path_for_schedule(
                snapshot=snapshot,
                schedule=assessment.intent_schedule,
                path_id=path_id,
                family="market_route",
                source_evidence_ids=routes_by_id[assessment.route_id].opportunity_ids,
            )
        )

    market_winner = _selected_market_assessment(plan)
    if market_winner is not None:
        winner_id = market_candidate_ids[market_winner.market_schedule_id]
        return (
            canonical_candidates,
            paths,
            winner_id,
            market_winner.intent_schedule,
            None,
            market_winner,
        )
    native_winner_id = MarketDailyEvaluationEngine.select_native_candidate_id(
        plan.native_observation
    )
    native_winner = native_by_id[native_winner_id]
    return (
        canonical_candidates,
        paths,
        native_winner_id,
        schedules[native_winner.intent_schedule_id],
        native_winner,
        None,
    )


def _commitment_target_reached(
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> bool:
    state = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == commitment.execution_scope_id
        ),
        None,
    )
    if state is None:
        return False
    if commitment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value:
        return state.current_stored_energy_wh <= commitment.target_energy_wh
    return state.current_stored_energy_wh >= commitment.target_energy_wh


def _committed_candidate(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> tuple[Candidate, EnergyPath]:
    state = next(
        item
        for item in snapshot.current_storage_states
        if item.execution_scope_id == commitment.execution_scope_id
    )
    stored_segments = commitment.segments or (
        CommittedPlanSegment(
            starts_at=commitment.starts_at,
            ends_at=commitment.ends_at,
            primitive=commitment.primitive,
            source_policy=(
                commitment.source_policy
                if commitment.source_policy != "not_applicable"
                else None
            ),
        ),
    )
    remaining_segments = tuple(
        item for item in stored_segments if item.ends_at > snapshot.captured_at
    )
    segments: list[PathSegment] = []
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == commitment.execution_scope_id
        and item.capability_id == state.capability_id
    )
    for order, stored in enumerate(remaining_segments, start=1):
        primitive = ExecutionPrimitive(stored.primitive)
        segments.append(
            PathSegment(
                segment_id=_id(
                    "mep-committed-segment",
                    f"{commitment.plan_id}|{order}|{stored.starts_at.isoformat()}",
                ),
                order=order,
                execution_scope_id=commitment.execution_scope_id,
                starts_at=max(snapshot.captured_at, stored.starts_at),
                ends_at=stored.ends_at,
                primitive=primitive,
                capability_id=state.capability_id,
                purpose="mep:retained_canonical_commitment",
                evidence_ids=(commitment.schedule_id or commitment.plan_id,),
                requested_power_w=(
                    limits.maximum_charge_input_power_w
                    if primitive is ExecutionPrimitive.CHARGE_AT_POWER
                    else limits.maximum_discharge_output_power_w
                    if primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
                    else None
                ),
                charge_source_policy=(
                    ChargeSourcePolicy(stored.source_policy)
                    if stored.source_policy is not None
                    else None
                ),
            )
        )
    path_id = _id("mep-committed-path", commitment.plan_id)
    path = EnergyPath(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        path_id=path_id,
        family="retained_commitment",
        segment_ids=tuple(item.segment_id for item in segments),
        segments=tuple(segments),
    )
    return (
        Candidate(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            candidate_id=_id("mep-committed-candidate", commitment.plan_id),
            energy_path_id=path_id,
            family="retained_commitment",
            pv_forecast_basis="committed-plan",
        ),
        path,
    )


def _first_action_phase(
    schedule: DailyReferenceIntentSchedule,
    captured_at: datetime,
) -> tuple[datetime, datetime, DailyStorageIntent] | None:
    actionable = {
        DailyStorageIntent.NOM,
        DailyStorageIntent.GRID_REQUIREMENT,
        DailyStorageIntent.STORAGE_EXPORT,
    }
    return next(
        (
            phase
            for phase in _coalesce(schedule.intervals)
            if phase[1] > captured_at and phase[2] in actionable
        ),
        None,
    )


def _persist_plan(
    *,
    store: ActivePlanCommitmentStore | None,
    snapshot: PlanningInputSnapshot,
    schedule: DailyReferenceIntentSchedule,
    plan_id: str,
    native: DailyReferenceCandidate | None,
    market: MarketRouteAssessment | None,
    prior_commitment: ActivePlanCommitment | None = None,
    selection_reason: str,
) -> None:
    if store is None or not snapshot.current_storage_states:
        return
    storage = snapshot.current_storage_states[0]
    phase = _first_action_phase(schedule, snapshot.captured_at)
    if phase is None:
        return
    starts_at, ends_at, intent = phase
    primitive, source_policy = _intent_primitive(intent)
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    if primitive is ExecutionPrimitive.DISCHARGE_AT_POWER:
        route = next(
            (
                item
                for item in (market.scenario_evidence if market is not None else ())
                if item.scenario.value == "lower"
            ),
            None,
        )
        target_energy_wh = (
            max(
                limits.minimum_soc * storage.usable_capacity_wh,
                route.storage_energy_at_horizon_end_wh,
            )
            if route is not None
            else limits.minimum_soc * storage.usable_capacity_wh
        )
    store.save(
        ActivePlanCommitment(
            execution_scope_id=storage.execution_scope_id,
            plan_id=plan_id,
            plan_revision=(
                prior_commitment.plan_revision + 1
                if prior_commitment is not None
                else 1
            ),
            primitive=primitive.value,
            source_policy=(
                source_policy.value if source_policy is not None else "not_applicable"
            ),
            starts_at=starts_at,
            ends_at=ends_at,
            target_energy_wh=target_energy_wh,
            selection_method_version=COMMITMENT_METHOD_VERSION,
            planner_id="mep",
            schedule_id=schedule.schedule_id,
            worst_case_financial_result_eur=(
                market.worst_case_incremental_result_eur
                if market is not None
                else (
                    native.worst_case_financial_result_eur
                    if native is not None
                    else None
                )
            ),
            average_charge_window_price_eur_per_kwh=(
                native.average_charge_window_price_eur_per_kwh
                if native is not None
                else None
            ),
            minimum_confidence=(native.minimum_confidence if native is not None else None),
            reserve_respected_across_scenarios=(
                native.reserve_respected_across_scenarios
                if native is not None
                else all(item.reserve_respected for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            target_held_across_scenarios=(
                native.target_held_across_scenarios
                if native is not None
                else all(item.target_held_at_horizon_end for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            minimum_storage_energy_at_horizon_end_wh=(
                min(item.storage_energy_at_horizon_end_wh for item in native.scenario_outcomes)
                if native is not None
                else min(item.storage_energy_at_horizon_end_wh for item in market.scenario_evidence)
                if market is not None
                else None
            ),
            segments=tuple(
                CommittedPlanSegment(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    primitive=primitive.value,
                    source_policy=(
                        source_policy.value
                        if source_policy is not None
                        else None
                    ),
                )
                for starts_at, ends_at, intent in _coalesce(schedule.intervals)
                for primitive, source_policy in (_intent_primitive(intent),)
            ),
            selection_reason=selection_reason,
            replaced_plan_id=(
                prior_commitment.plan_id
                if prior_commitment is not None
                else None
            ),
        )
    )


def build_mep_canonical_run(
    *,
    snapshot: PlanningInputSnapshot,
    opportunities: OpportunitySet,
    planner_runtime: MarketDailyPlannerRuntime,
    commitment_store: ActivePlanCommitmentStore | None,
    control_change_allowed: bool,
    switching_margin_eur: float,
) -> tuple[CanonicalPipelineRun, MepCanonicalStageTimings, MarketDailyRuntimeOutcome]:
    stage_started = perf_counter()
    planner_outcome = planner_runtime.generate(
        snapshot,
        opportunities=opportunities,
    )
    evaluated_plan = (
        MarketDailyEvaluationEngine().evaluate(
            snapshot=snapshot,
            portfolio=planner_outcome.portfolio,
            dispatch_authority=False,
        )
        if planner_outcome.portfolio is not None
        else None
    )
    if evaluated_plan is None:
        candidates: list[Candidate] = []
        paths: list[EnergyPath] = []
        winner_id = None
        selected_schedule = None
        native_winner = None
        market_winner = None
    else:
        (
            candidates,
            paths,
            winner_id,
            selected_schedule,
            native_winner,
            market_winner,
        ) = _plan_candidates(snapshot, evaluated_plan)
    candidate_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    retained_commitment = next(iter(snapshot.active_plan_commitments), None)
    if retained_commitment is not None and _commitment_target_reached(
        snapshot,
        retained_commitment,
    ):
        if commitment_store is not None:
            commitment_store.clear(retained_commitment.execution_scope_id)
        retained_commitment = None
    challenger_financial_result = (
        market_winner.worst_case_incremental_result_eur
        if market_winner is not None
        else native_winner.worst_case_financial_result_eur
        if native_winner is not None
        else None
    )
    commitment_decision = MarketDailyEvaluationEngine.evaluate_commitment(
        snapshot=snapshot,
        incumbent=retained_commitment,
        challenger_financial_result_eur=challenger_financial_result,
        required_by=planner_outcome.required_by,
        switching_margin_eur=switching_margin_eur,
    )
    replacement_reason = (
        commitment_decision.decisive_step
        if not commitment_decision.incumbent_retained
        else None
    )
    incumbent_retained = commitment_decision.incumbent_retained
    if incumbent_retained and retained_commitment is not None:
        committed_candidate, committed_path = _committed_candidate(
            snapshot=snapshot,
            commitment=retained_commitment,
        )
        candidates.append(committed_candidate)
        paths.append(committed_path)
        winner_id = committed_candidate.candidate_id
    winner = next((item for item in candidates if item.candidate_id == winner_id), None)
    winning_path = next(
        (item for item in paths if winner is not None and item.path_id == winner.energy_path_id),
        None,
    )
    candidate_set = CandidateSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=_id("mep-candidate-set", opportunities.opportunity_set_id),
        candidates=tuple(candidates),
        energy_paths=tuple(paths),
        derivation_status=("ready" if winner is not None else "blocked"),
        derivation_reason=(None if winner is not None else planner_outcome.reason),
    )
    outcomes = CandidateOutcomeSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=candidate_set.candidate_set_id,
        outcome_set_id=_id("mep-outcome-set", candidate_set.candidate_set_id),
        candidate_ids=tuple(item.candidate_id for item in candidates),
    )
    evaluation = EvaluationRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=_id("mep-evaluation", outcomes.outcome_set_id),
        candidate_set_id=candidate_set.candidate_set_id,
        winning_candidate_id=(winner.candidate_id if winner is not None else None),
        winning_energy_path_id=(winning_path.path_id if winning_path is not None else None),
        reason=(
            "active canonical MEP plan commitment retained"
            if incumbent_retained
            else evaluated_plan.reason
            if evaluated_plan is not None
            else planner_outcome.reason or "mep_planning_blocked"
        ),
        status=("winner_selected" if winner is not None else "fallback_active"),
        evaluated_candidate_ids=tuple(item.candidate_id for item in candidates),
        decisive_step=(
            "stability:canonical_plan_commitment_retained"
            if incumbent_retained
            else replacement_reason
            if replacement_reason is not None
            else "objective:mep_physical_and_market_evaluation"
            if winner is not None
            else "fallback:mep_planning_blocked"
        ),
    )
    evaluation_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    plans: list[ObserverExecutionPlan] = []
    if winner is not None and winning_path is not None and winning_path.segments:
        scope_id = winning_path.segments[0].execution_scope_id
        due = next(
            (
                item
                for item in winning_path.segments
                if item.starts_at <= snapshot.captured_at < item.ends_at
            ),
            winning_path.segments[0],
        )
        plan_id = (
            retained_commitment.plan_id
            if incumbent_retained and retained_commitment is not None
            else _id(
                "mep-plan",
                (
                    f"{evaluation.evaluation_id}|{winning_path.path_id}|"
                    f"revision:{retained_commitment.plan_revision + 1}"
                    if replacement_reason is not None
                    and retained_commitment is not None
                    else f"{evaluation.evaluation_id}|{winning_path.path_id}"
                ),
            )
        )
        plans.append(
            ObserverExecutionPlan(
                plan_id=plan_id,
                evaluation_id=evaluation.evaluation_id,
                winning_candidate_id=winner.candidate_id,
                winning_energy_path_id=winning_path.path_id,
                execution_scope_id=scope_id,
                valid_from=min(item.starts_at for item in winning_path.segments),
                valid_until=max(item.ends_at for item in winning_path.segments),
                planned_primitive=due.primitive,
                planned_vendor_mode=None,
                lifecycle_status=(
                    "due"
                    if due.starts_at <= snapshot.captured_at < due.ends_at
                    else "scheduled"
                ),
                observer_only=not control_change_allowed,
                segments=tuple(
                    ObserverExecutionPlanSegment(
                        segment_id=_id("mep-plan-segment", item.segment_id),
                        source_path_segment_id=item.segment_id,
                        order=index,
                        starts_at=item.starts_at,
                        ends_at=item.ends_at,
                        primitive=item.primitive,
                        capability_id=item.capability_id,
                        purpose=item.purpose,
                        evidence_ids=item.evidence_ids,
                        requested_power_w=item.requested_power_w,
                        charge_source_policy=item.charge_source_policy,
                        planned_vendor_mode=None,
                    )
                    for index, item in enumerate(winning_path.segments, start=1)
                ),
            )
        )
        if not incumbent_retained and selected_schedule is not None:
            _persist_plan(
                store=commitment_store,
                snapshot=snapshot,
                schedule=selected_schedule,
                plan_id=plan_id,
                native=native_winner,
                market=market_winner,
                prior_commitment=(
                    retained_commitment
                    if replacement_reason is not None
                    else None
                ),
                selection_reason=(
                    evaluation.decisive_step
                    or "objective:mep_physical_and_market_evaluation"
                ),
            )
    execution_plan_set = ExecutionPlanSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        plan_set_id=_id("mep-plan-set", evaluation.evaluation_id),
        evaluation_id=evaluation.evaluation_id,
        winning_energy_path_id=evaluation.winning_energy_path_id,
        plan_ids=tuple(item.plan_id for item in plans),
        plans=tuple(plans),
    )
    execution_plan_builder_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    execution_record = ExecutionRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        execution_record_id=_id("mep-execution", execution_plan_set.plan_set_id),
        plan_set_id=execution_plan_set.plan_set_id,
        status=(
            "live_plan_ready"
            if plans and control_change_allowed
            else "observer_only_plan_ready"
            if plans
            else "fallback_active"
        ),
        reason=(evaluation.reason if plans else "no executable MEP plan"),
    )
    execution_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    due_segment = next(
        (
            segment
            for plan in plans
            for segment in plan.segments
            if segment.starts_at <= snapshot.captured_at < segment.ends_at
        ),
        None,
    )
    mode_evidence = snapshot.storage_mode_capability_evidence
    provenance = snapshot.storage_mode_control_provenance
    blockers: list[str] = []
    if due_segment is not None:
        if mode_evidence is None:
            blockers.append("storage_mode_capability_evidence_unavailable")
        if (
            snapshot.bms_calibration_evidence is not None
            and snapshot.bms_calibration_evidence.active
        ):
            blockers.append("bms_soc_calibration_active")
        if provenance is None:
            blockers.append("manual_override_provenance_unverified")
        elif provenance.manual_override_active:
            blockers.append("manual_override_active")
        if not control_change_allowed:
            blockers.append("observer_only_authority")
    request_ready = due_segment is not None and blockers in ([], ["observer_only_authority"])
    request_id = (
        _id(
            "mep-primitive-request",
            f"{execution_record.execution_record_id}|{due_segment.segment_id}",
        )
        if request_ready and due_segment is not None
        else None
    )
    primitive_boundary = ExecutionPrimitiveBoundary(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        request_id=request_id,
        execution_record_id=execution_record.execution_record_id,
        status=(
            "request_ready"
            if request_ready and control_change_allowed
            else "observer_request_ready"
            if request_ready
            else "dry_run_blocked"
            if due_segment is not None
            else "not_emitted"
        ),
        planned_primitive=(due_segment.primitive if due_segment is not None else None),
        mapping_status=("pending_adapter" if request_id is not None else "not_requested"),
        source_entity_id=(
            mode_evidence.source_entity_id if mode_evidence is not None else None
        ),
        current_vendor_mode=(
            mode_evidence.current_vendor_mode if mode_evidence is not None else None
        ),
        planned_vendor_mode=None,
        mapping_method_version=(
            mode_evidence.method_version if mode_evidence is not None else None
        ),
        blockers=tuple(blockers),
    )
    execution_primitive_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    adapter_boundary = DeviceAdapterBoundary(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        translation_id=None,
        primitive_request_id=None,
        status="not_invoked",
    )
    device_adapter_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    vendor_result = VendorBoundaryResult(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        command_id=None,
        adapter_translation_id=None,
        status="not_dispatched",
        dispatch_intent_id=None,
        target_entity_id=None,
        planned_vendor_mode=None,
    )
    vendor_result_ms = round((perf_counter() - stage_started) * 1000.0, 3)
    return (
        CanonicalPipelineRun(
            planning_input=snapshot,
            opportunities=opportunities,
            candidate_set=candidate_set,
            outcomes=outcomes,
            evaluation=evaluation,
            execution_plan_set=execution_plan_set,
            execution_record=execution_record,
            primitive_boundary=primitive_boundary,
            adapter_boundary=adapter_boundary,
            vendor_result=vendor_result,
        ),
        MepCanonicalStageTimings(
            candidate_engine_ms=candidate_engine_ms,
            evaluation_engine_ms=evaluation_engine_ms,
            execution_plan_builder_ms=execution_plan_builder_ms,
            execution_engine_ms=execution_engine_ms,
            execution_primitive_ms=execution_primitive_ms,
            device_adapter_ms=device_adapter_ms,
            vendor_result_ms=vendor_result_ms,
        ),
        planner_outcome,
    )
