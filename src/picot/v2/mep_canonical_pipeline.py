"""Canonical stage composition for the sole Markt Etmaal Planner."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from time import perf_counter

from picot.architecture_ownership import architecture_ownership
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_candidate import DailyReferenceCandidate
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.energy_path import PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.market_daily_planner import (
    MarketDailyCandidatePortfolio,
    MarketDailyPlan,
    MarketRouteAssessment,
)
from picot.planner.mep_candidate_outcomes import produce_mep_comparable_portfolio
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
    OpportunitySet,
    PlanningInputSnapshot,
    VendorBoundaryResult,
)
from picot.v2.execution_plan_projection import project_execution_plan_set
from picot.v2.market_daily_runtime import (
    MarketDailyPlannerRuntime,
    MarketDailyRuntimeOutcome,
)
from picot.v2.plan_commitment_store import (
    COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedHouseholdLoadInterval,
    CommittedPlanSegment,
    CommittedStorageEnergyCheckpoint,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("pipeline_composition", __name__)


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
        if phases and phases[-1][1] == interval.starts_at and phases[-1][2] is interval.intent:
            phases[-1] = (phases[-1][0], interval.ends_at, interval.intent)
        else:
            phases.append((interval.starts_at, interval.ends_at, interval.intent))
    return tuple(phases)


def _coalesce_committed_segments(
    segments: tuple[CommittedPlanSegment, ...],
) -> tuple[CommittedPlanSegment, ...]:
    coalesced: list[CommittedPlanSegment] = []
    for segment in segments:
        if (
            coalesced
            and coalesced[-1].ends_at == segment.starts_at
            and coalesced[-1].primitive == segment.primitive
            and coalesced[-1].source_policy == segment.source_policy
            and coalesced[-1].storage_export_target_wh is None
            and segment.storage_export_target_wh is None
        ):
            coalesced[-1] = replace(coalesced[-1], ends_at=segment.ends_at)
        else:
            coalesced.append(segment)
    return tuple(coalesced)


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
    has_future_export = any(
        segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
        for segment in commitment.segments
    )
    if has_future_export:
        return False
    if commitment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value:
        return state.current_stored_energy_wh <= commitment.target_energy_wh
    return state.current_stored_energy_wh >= commitment.target_energy_wh


def _has_future_export(
    commitment: ActivePlanCommitment,
    captured_at: datetime,
) -> bool:
    return any(
        segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > captured_at
        for segment in commitment.segments
    )


def _complete_acquisition_revision(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> ActivePlanCommitment | None:
    """Remove completed charge phases without discarding later export."""

    state = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == commitment.execution_scope_id
        ),
        None,
    )
    future_exports = tuple(
        segment
        for segment in commitment.segments
        if segment.primitive == ExecutionPrimitive.DISCHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
    )
    future_charges = tuple(
        segment
        for segment in commitment.segments
        if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
        and segment.ends_at > snapshot.captured_at
    )
    has_acquisition_before_export = any(
        charge.ends_at <= export.starts_at for charge in future_charges for export in future_exports
    )

    def is_pre_export_acquisition(segment: CommittedPlanSegment) -> bool:
        return segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value and any(
            segment.ends_at <= export.starts_at for export in future_exports
        )

    if (
        state is None
        or state.current_stored_energy_wh + 1e-6 < commitment.target_energy_wh
        or not future_exports
        or not future_charges
        or not has_acquisition_before_export
    ):
        return None
    revised_segments = _coalesce_committed_segments(
        tuple(
            replace(
                segment,
                starts_at=max(segment.starts_at, snapshot.captured_at),
                primitive=(
                    ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value
                    if is_pre_export_acquisition(segment)
                    else segment.primitive
                ),
                source_policy=(
                    ChargeSourcePolicy.PV_ONLY.value
                    if is_pre_export_acquisition(segment)
                    else segment.source_policy
                ),
            )
            for segment in commitment.segments
            if segment.ends_at > snapshot.captured_at
        )
    )
    return replace(
        commitment,
        plan_id=_id(
            "mep-plan-revision",
            f"{commitment.plan_id}|acquisition-complete|{snapshot.captured_at.isoformat()}",
        ),
        plan_revision=commitment.plan_revision + 1,
        primitive=revised_segments[0].primitive,
        source_policy=(revised_segments[0].source_policy or "not_applicable"),
        starts_at=revised_segments[0].starts_at,
        ends_at=revised_segments[-1].ends_at,
        segments=revised_segments,
        selection_reason="execution_feedback:acquisition_target_reached",
        replaced_plan_id=commitment.plan_id,
    )


def _defer_charge_revision(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
) -> ActivePlanCommitment | None:
    """Move a PV-covered due charge phase to the last safe fallback slot."""

    segments = list(commitment.segments)
    due_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if segment.primitive == ExecutionPrimitive.CHARGE_AT_POWER.value
            and segment.starts_at <= snapshot.captured_at < segment.ends_at
        ),
        None,
    )
    if due_index is None or due_index + 1 >= len(segments):
        return None
    due = segments[due_index]
    following = segments[due_index + 1]
    if following.primitive != ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value:
        return None
    duration = due.ends_at - snapshot.captured_at
    canonical_interval = timedelta(minutes=15)
    shifted_end = following.ends_at - canonical_interval
    shifted_start = shifted_end - duration
    if shifted_start <= snapshot.captured_at:
        return None
    revised: list[CommittedPlanSegment] = []
    revised.extend(
        segment for segment in segments[:due_index] if segment.ends_at > snapshot.captured_at
    )
    revised.append(
        CommittedPlanSegment(
            starts_at=snapshot.captured_at,
            ends_at=shifted_start,
            primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value,
            source_policy=ChargeSourcePolicy.PV_ONLY.value,
        )
    )
    revised.append(replace(due, starts_at=shifted_start, ends_at=shifted_end))
    revised.append(replace(following, starts_at=shifted_end))
    revised.extend(segments[due_index + 2 :])
    revised_segments = _coalesce_committed_segments(tuple(revised))
    return replace(
        commitment,
        plan_id=_id(
            "mep-plan-revision",
            f"{commitment.plan_id}|pv-deferred|{snapshot.captured_at.isoformat()}",
        ),
        plan_revision=commitment.plan_revision + 1,
        primitive=revised_segments[0].primitive,
        source_policy=(revised_segments[0].source_policy or "not_applicable"),
        starts_at=revised_segments[0].starts_at,
        ends_at=revised_segments[-1].ends_at,
        segments=revised_segments,
        selection_reason=("execution_feedback:measured_pv_progress_covers_grid_charge"),
        replaced_plan_id=commitment.plan_id,
    )


def _overlap_fraction(
    starts_at: datetime,
    ends_at: datetime,
    window_starts_at: datetime,
    window_ends_at: datetime,
) -> float:
    overlap_starts_at = max(starts_at, window_starts_at)
    overlap_ends_at = min(ends_at, window_ends_at)
    if overlap_ends_at <= overlap_starts_at:
        return 0.0
    return (overlap_ends_at - overlap_starts_at).total_seconds() / (
        ends_at - starts_at
    ).total_seconds()


def _measured_pv_basis_covers_remaining_acquisition(
    *,
    snapshot: PlanningInputSnapshot,
    path: EnergyPath,
    due_segment: PathSegment,
) -> bool:
    """Keep NOM when measured-PV promotion already proves target recovery.

    The daily measured-PV stage expresses a central promotion by replacing the
    remaining current-day lower lane with central. This gate consumes that
    canonical evidence without selecting a new forecast basis. It is deliberately
    conservative: incomplete ranges, a non-NOM current mode, or insufficient
    lower-lane surplus all leave the approved explicit charge request untouched.
    """

    if due_segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
        return False
    mode = snapshot.storage_mode_capability_evidence
    if mode is None or mode.current_vendor_mode != "Nul op de meter":
        return False
    if snapshot.pv_energy_timeline is None or snapshot.household_load_forecast is None:
        return False
    storage = next(
        (
            item
            for item in snapshot.current_storage_states
            if item.execution_scope_id == due_segment.execution_scope_id
        ),
        None,
    )
    limits = next(
        (
            item
            for item in snapshot.storage_physical_limits
            if item.execution_scope_id == due_segment.execution_scope_id
            and storage is not None
            and item.capability_id == storage.capability_id
        ),
        None,
    )
    if storage is None or limits is None:
        return False
    ordered = tuple(sorted(path.segments, key=lambda item: item.order))
    due_index = next(
        (index for index, item in enumerate(ordered) if item.segment_id == due_segment.segment_id),
        None,
    )
    if due_index is None:
        return False
    acquisition_end = due_segment.ends_at
    for segment in ordered[due_index + 1 :]:
        if segment.starts_at != acquisition_end or segment.primitive not in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        }:
            break
        acquisition_end = segment.ends_at
    window_start = snapshot.captured_at
    future_pv = tuple(
        item
        for item in snapshot.pv_energy_timeline.intervals
        if item.ends_at > window_start and item.starts_at < acquisition_end
    )
    if not future_pv or any(
        item.forecast_lower_energy_wh is None
        or item.forecast_central_energy_wh is None
        or abs(item.forecast_lower_energy_wh - item.forecast_central_energy_wh) > 1e-6
        for item in future_pv
    ):
        return False
    pv_surplus_wh = sum(
        (item.forecast_lower_energy_wh or 0.0)
        * _overlap_fraction(
            item.starts_at,
            item.ends_at,
            window_start,
            acquisition_end,
        )
        for item in future_pv
    ) - sum(
        item.expected_energy_wh
        * _overlap_fraction(
            item.starts_at,
            item.ends_at,
            window_start,
            acquisition_end,
        )
        for item in snapshot.household_load_forecast.intervals
    )
    rte = snapshot.storage_round_trip_efficiency
    conservative_charge_efficiency = (
        rte.round_trip_efficiency
        if rte is not None and rte.status == "available" and rte.round_trip_efficiency is not None
        else 0.8
    )
    projected_energy_wh = (
        storage.current_stored_energy_wh
        + max(
            0.0,
            pv_surplus_wh,
        )
        * conservative_charge_efficiency
    )
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    return projected_energy_wh + 1e-6 >= target_energy_wh


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


def _committed_storage_energy_checkpoints(
    *,
    plan: MarketDailyPlan | MarketDailyCandidatePortfolio,
    schedule: DailyReferenceIntentSchedule,
    market: MarketRouteAssessment | None,
) -> tuple[CommittedStorageEnergyCheckpoint, ...]:
    by_scenario: dict[str, dict[datetime, float]] = {}
    if market is not None:
        by_scenario = {
            evidence.scenario.value: {
                checkpoint.at: checkpoint.energy_wh
                for checkpoint in evidence.storage_energy_checkpoints
            }
            for evidence in market.scenario_evidence
        }
    else:
        strategy_result = next(
            (
                item
                for item in (plan.native_observation.observer_result.portfolio.strategy_results)
                if item.intent_schedule.schedule_id == schedule.schedule_id
            ),
            None,
        )
        if strategy_result is not None:
            by_scenario = {
                trajectory.scenario.value: {
                    interval.ends_at: interval.storage_energy_at_end_wh
                    for interval in trajectory.intervals
                }
                for trajectory in strategy_result.run.simulation.trajectories
            }

    required = {"lower", "central", "upper"}
    if set(by_scenario) != required:
        return ()
    checkpoint_times = set(by_scenario["lower"])
    checkpoint_times.intersection_update(by_scenario["central"])
    checkpoint_times.intersection_update(by_scenario["upper"])
    return tuple(
        CommittedStorageEnergyCheckpoint(
            at=at,
            lower_energy_wh=by_scenario["lower"][at],
            central_energy_wh=by_scenario["central"][at],
            upper_energy_wh=by_scenario["upper"][at],
        )
        for at in sorted(checkpoint_times)
    )


def _persist_plan(
    *,
    store: ActivePlanCommitmentStore | None,
    snapshot: PlanningInputSnapshot,
    plan: MarketDailyPlan | MarketDailyCandidatePortfolio,
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
    action_phase = _first_action_phase(schedule, snapshot.captured_at)
    if action_phase is None:
        return
    coalesced_segments = _coalesce(schedule.intervals)
    starts_at, _first_ends_at, first_intent = coalesced_segments[0]
    primitive, source_policy = _intent_primitive(first_intent)
    action_primitive, _action_source_policy = _intent_primitive(action_phase[2])
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    if action_primitive is ExecutionPrimitive.DISCHARGE_AT_POWER:
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
    storage_energy_checkpoints = _committed_storage_energy_checkpoints(
        plan=plan,
        schedule=schedule,
        market=market,
    )
    household_load_intervals = tuple(
        CommittedHouseholdLoadInterval(
            interval_id=interval.interval_id,
            starts_at=interval.starts_at,
            ends_at=interval.ends_at,
            expected_energy_wh=interval.expected_energy_wh,
            confidence=interval.confidence,
            source_reference=interval.source_reference,
            method_version=interval.method_version,
        )
        for interval in (
            snapshot.household_load_forecast.intervals
            if snapshot.household_load_forecast is not None
            else ()
        )
        if interval.starts_at >= snapshot.captured_at
        and interval.ends_at <= coalesced_segments[-1][1]
    )
    if not household_load_intervals or not storage_energy_checkpoints:
        raise ValueError(
            "an admitted plan requires committed household-load and storage-energy "
            "materiality baselines"
        )
    store.save(
        ActivePlanCommitment(
            execution_scope_id=storage.execution_scope_id,
            plan_id=plan_id,
            plan_revision=(
                prior_commitment.plan_revision + 1 if prior_commitment is not None else 1
            ),
            primitive=primitive.value,
            source_policy=(source_policy.value if source_policy is not None else "not_applicable"),
            starts_at=starts_at,
            # A market commitment owns its complete lifecycle.  Expiring it at
            # the end of the first charge phase silently discards a later
            # export phase.
            ends_at=coalesced_segments[-1][1],
            target_energy_wh=target_energy_wh,
            selection_method_version=COMMITMENT_METHOD_VERSION,
            planner_id="mep",
            schedule_id=schedule.schedule_id,
            worst_case_financial_result_eur=(
                market.worst_case_incremental_result_eur
                if market is not None
                else (native.worst_case_financial_result_eur if native is not None else None)
            ),
            average_charge_window_price_eur_per_kwh=(
                native.average_charge_window_price_eur_per_kwh if native is not None else None
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
            segments=_coalesce_committed_segments(
                tuple(
                    CommittedPlanSegment(
                        starts_at=interval.starts_at,
                        ends_at=interval.ends_at,
                        primitive=primitive.value,
                        source_policy=(source_policy.value if source_policy is not None else None),
                        storage_export_target_wh=(
                            interval.storage_export_target_wh
                            if interval.intent is DailyStorageIntent.STORAGE_EXPORT
                            else None
                        ),
                    )
                    for interval in schedule.intervals
                    for primitive, source_policy in (_intent_primitive(interval.intent),)
                )
            ),
            selection_reason=selection_reason,
            replaced_plan_id=(prior_commitment.plan_id if prior_commitment is not None else None),
            selected_at=snapshot.captured_at,
            household_load_intervals=household_load_intervals,
            storage_energy_checkpoints=storage_energy_checkpoints,
            candidate_family=(
                "market_route"
                if market is not None
                else native.family.value
                if native is not None
                else "unknown"
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
    retained_commitment = next(iter(snapshot.active_plan_commitments), None)
    if retained_commitment is not None:
        completed_revision = _complete_acquisition_revision(
            snapshot=snapshot,
            commitment=retained_commitment,
        )
        if completed_revision is not None:
            retained_commitment = completed_revision
            if commitment_store is not None:
                commitment_store.save(completed_revision)
    if retained_commitment is not None and _commitment_target_reached(
        snapshot,
        retained_commitment,
    ):
        if commitment_store is not None:
            commitment_store.clear(retained_commitment.execution_scope_id)
        retained_commitment = None
    snapshot = replace(
        snapshot,
        active_plan_commitments=((retained_commitment,) if retained_commitment is not None else ()),
    )

    stage_started = perf_counter()
    planner_outcome = planner_runtime.generate(
        snapshot,
        opportunities=opportunities,
        comparison_horizon_end=(
            retained_commitment.ends_at if retained_commitment is not None else None
        ),
    )
    comparable = None
    if planner_outcome.portfolio is not None:
        try:
            conversion_model, _ = planner_runtime.planning_configuration(snapshot)
            comparable = produce_mep_comparable_portfolio(
                snapshot=snapshot,
                portfolio=planner_outcome.portfolio,
                conversion_model=conversion_model,
                incumbent=retained_commitment,
                financial_equivalence_margin_eur=switching_margin_eur,
            )
        except Exception as exc:
            planner_outcome = replace(
                planner_outcome,
                status="blocked",
                reason=str(exc) or exc.__class__.__name__,
                portfolio=None,
            )
    if comparable is None:
        candidates: list[Candidate] = []
        paths: list[EnergyPath] = []
        winner_id: str | None = None
        selected_schedule = None
        native_winner = None
        market_winner = None
    else:
        candidates = [
            Candidate(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                candidate_id=item.candidate_id,
                energy_path_id=item.energy_path_id,
                family=item.family.value,
                pv_forecast_basis="lower-central-upper",
            )
            for item in comparable.candidate_set.candidates
        ]
        paths = [
            EnergyPath(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                path_id=item.path_id,
                family=item.family.value,
                segment_ids=tuple(segment.segment_id for segment in item.segments),
                segments=item.segments,
                projected_states=item.projected_states,
                capability_confidence=item.confidence,
            )
            for item in comparable.candidate_set.energy_paths
        ]
        selected_schedule = None
        native_winner = None
        market_winner = None
    candidate_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    canonical_evaluation = (
        EvaluationEngine().evaluate(
            comparable.candidate_set,
            comparable.strategy,
            comparable.outcome_set,
            created_at=snapshot.captured_at,
            incumbent_candidate_id=comparable.incumbent_candidate_id,
            financial_equivalence_margin=switching_margin_eur,
        )
        if comparable is not None
        else None
    )
    winner_id = (
        canonical_evaluation.record.winning_candidate_id
        if canonical_evaluation is not None
        else None
    )
    incumbent_retained = (
        comparable is not None
        and comparable.incumbent_candidate_id is not None
        and winner_id == comparable.incumbent_candidate_id
    )
    replacement_reason = (
        canonical_evaluation.record.decisive_step
        if canonical_evaluation is not None
        and comparable is not None
        and comparable.incumbent_candidate_id is not None
        and not incumbent_retained
        else None
    )
    if comparable is not None and winner_id is not None:
        source = next(item for item in comparable.sources if item.candidate_id == winner_id)
        selected_schedule = source.schedule
        native_winner = source.native_candidate
        market_winner = source.market_assessment
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
        projected_balances=(
            (comparable.projected_balance,) if comparable is not None else ()
        ),
        storage_requirements=(
            (comparable.storage_requirement,) if comparable is not None else ()
        ),
        derivation_status=("ready" if winner is not None else "blocked"),
        derivation_reason=(None if winner is not None else planner_outcome.reason),
    )
    outcomes = CandidateOutcomeSet(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        candidate_set_id=candidate_set.candidate_set_id,
        outcome_set_id=_id("mep-outcome-set", candidate_set.candidate_set_id),
        candidate_ids=tuple(item.candidate_id for item in candidates),
        outcomes=(comparable.diagnostic_outcomes if comparable is not None else ()),
    )
    decisive_step = (
        canonical_evaluation.record.decisive_step
        if canonical_evaluation is not None
        else "fallback:mep_planning_blocked"
    )
    evaluation = EvaluationRecord(
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        evaluation_id=(
            canonical_evaluation.record.evaluation_id
            if canonical_evaluation is not None
            else _id("mep-evaluation", outcomes.outcome_set_id)
        ),
        candidate_set_id=candidate_set.candidate_set_id,
        winning_candidate_id=(winner.candidate_id if winner is not None else None),
        winning_energy_path_id=(winning_path.path_id if winning_path is not None else None),
        reason=(
            "active canonical MEP plan commitment retained"
            if incumbent_retained
            else decisive_step or "evaluation:winner_selected"
            if winner is not None
            else planner_outcome.reason or "mep_planning_blocked"
        ),
        status=("winner_selected" if winner is not None else "fallback_active"),
        evaluated_candidate_ids=(
            canonical_evaluation.record.evaluated_candidate_ids
            if canonical_evaluation is not None
            else ()
        ),
        decisive_step=decisive_step,
        incumbent_candidate_id=(
            comparable.incumbent_candidate_id if comparable is not None else None
        ),
        financial_equivalence_margin_eur=switching_margin_eur,
        commitment_decision=(
            "retained"
            if incumbent_retained
            else "replaced"
            if comparable is not None and comparable.incumbent_candidate_id is not None
            else "not_applicable"
        ),
    )
    evaluation_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

    stage_started = perf_counter()
    canonical_plan_set = (
        ExecutionPlanBuilder().build(
            canonical_evaluation,
            created_at=snapshot.captured_at,
            fallback_policy_id="mep-safe-fallback:v1",
        )
        if canonical_evaluation is not None
        and canonical_evaluation.winning_energy_path is not None
        else None
    )
    admitted_plan_ids_by_scope = (
        {retained_commitment.execution_scope_id: retained_commitment.plan_id}
        if incumbent_retained and retained_commitment is not None
        else {}
    )
    if canonical_plan_set is not None:
        execution_plan_set = project_execution_plan_set(
            canonical_plan_set,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            observer_only=not control_change_allowed,
            admitted_plan_ids_by_scope=admitted_plan_ids_by_scope,
        )
    else:
        execution_plan_set = ExecutionPlanSet(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            plan_set_id=_id("mep-plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
        )
    plans = list(execution_plan_set.plans)
    if plans:
        plan_id = plans[0].plan_id
        if (
            not incumbent_retained
            and selected_schedule is not None
            and planner_outcome.portfolio is not None
        ):
            _persist_plan(
                store=commitment_store,
                snapshot=snapshot,
                plan=planner_outcome.portfolio,
                schedule=selected_schedule,
                plan_id=plan_id,
                native=native_winner,
                market=market_winner,
                prior_commitment=(retained_commitment if replacement_reason is not None else None),
                selection_reason=(
                    evaluation.decisive_step or "objective:mep_physical_and_market_evaluation"
                ),
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
    due_path_segment = next(
        (
            item
            for item in (winning_path.segments if winning_path is not None else ())
            if due_segment is not None and item.segment_id == due_segment.source_path_segment_id
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
        if (
            winning_path is not None
            and due_path_segment is not None
            and _measured_pv_basis_covers_remaining_acquisition(
                snapshot=snapshot,
                path=winning_path,
                due_segment=due_path_segment,
            )
        ):
            blockers.append("measured_pv_progress_covers_grid_charge")
        if not control_change_allowed:
            blockers.append("observer_only_authority")
    request_ready = due_segment is not None and blockers in ([], ["observer_only_authority"])
    measured_progress_deferred = blockers == ["measured_pv_progress_covers_grid_charge"]
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
            else "execution_deferred"
            if measured_progress_deferred
            else "dry_run_blocked"
            if due_segment is not None
            else "not_emitted"
        ),
        planned_primitive=(due_segment.primitive if due_segment is not None else None),
        mapping_status=("pending_adapter" if request_id is not None else "not_requested"),
        source_entity_id=(mode_evidence.source_entity_id if mode_evidence is not None else None),
        current_vendor_mode=(
            mode_evidence.current_vendor_mode if mode_evidence is not None else None
        ),
        planned_vendor_mode=None,
        mapping_method_version=(
            mode_evidence.method_version if mode_evidence is not None else None
        ),
        blockers=tuple(blockers),
    )
    if measured_progress_deferred and commitment_store is not None and due_path_segment is not None:
        active_commitment = commitment_store.load(due_path_segment.execution_scope_id)
        if active_commitment is not None:
            deferred_revision = _defer_charge_revision(
                snapshot=snapshot,
                commitment=active_commitment,
            )
            if deferred_revision is not None:
                commitment_store.save(deferred_revision)
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
