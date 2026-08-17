"""Minimal end-to-end PicoT v2 canonical pipeline.

Canonical v2 pipeline implementation; diagnostic timing is layered around this path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import perf_counter

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.candidate_engine import CandidateEngine, CandidateInputError
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    CanonicalPipelineRun,
    DelegatedStorageCandidateOutcome,
    DeviceAdapterBoundary,
    EnergyPath,
    EvaluationRecord,
    ExecutionPlanSet,
    ExecutionPrimitiveBoundary,
    ExecutionRecord,
    ObserverExecutionPlan,
    ObserverExecutionPlanSegment,
    PlanningInputSnapshot,
    VendorBoundaryResult,
)
from picot.v2.delegated_storage_candidates import (
    construct_pv_charge_only_candidate,
)
from picot.v2.delegated_storage_outcomes import (
    simulate_pv_charge_only_outcomes,
)
from picot.v2.opportunity_engine import OpportunityEngine, PriceOpportunityConfig
from picot.v2.pv_forecast_assumptions import (
    derive_pv_forecast_basis_assumptions,
)


def _id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _bootstrap_snapshot(captured_at: datetime | None = None) -> PlanningInputSnapshot:
    now = captured_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    run_seed = f"{__version__}|{now.isoformat()}|{ARCHITECTURE_BASELINE_COMMIT}"
    run_id = _id("run", run_seed)
    snapshot_id = _id("snapshot", run_id)
    return PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=snapshot_id,
        captured_at=now,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
    )


@dataclass(frozen=True, slots=True)
class PipelineStageTimings:
    """Passive wall-clock timings for canonical stages 02 through 09."""

    opportunity_engine_ms: float
    candidate_engine_ms: float
    evaluation_engine_ms: float
    execution_plan_builder_ms: float
    execution_engine_ms: float
    execution_primitive_ms: float
    device_adapter_ms: float
    vendor_result_ms: float
    canonical_total_ms: float


class CanonicalPipeline:
    """Execute the accepted route exactly once for one immutable run."""

    def __init__(
        self,
        *,
        opportunity_engine: OpportunityEngine | None = None,
        candidate_engine: CandidateEngine | None = None,
    ) -> None:
        self._opportunity_engine = opportunity_engine or OpportunityEngine()
        self._candidate_engine = candidate_engine or CandidateEngine()

    def run(
        self,
        *,
        planning_input: PlanningInputSnapshot | None = None,
        captured_at: datetime | None = None,
        price_opportunity_config: PriceOpportunityConfig | None = None,
        control_change_allowed: bool = False,
    ) -> CanonicalPipelineRun:
        run, _ = self._execute(
            planning_input=planning_input,
            captured_at=captured_at,
            price_opportunity_config=price_opportunity_config,
            control_change_allowed=control_change_allowed,
        )
        return run

    def run_timed(
        self,
        *,
        planning_input: PlanningInputSnapshot | None = None,
        captured_at: datetime | None = None,
        price_opportunity_config: PriceOpportunityConfig | None = None,
        control_change_allowed: bool = False,
    ) -> tuple[CanonicalPipelineRun, PipelineStageTimings]:
        """Execute the canonical route and return passive stage timings."""
        return self._execute(
            planning_input=planning_input,
            captured_at=captured_at,
            price_opportunity_config=price_opportunity_config,
            control_change_allowed=control_change_allowed,
        )

    def _execute(
        self,
        *,
        planning_input: PlanningInputSnapshot | None,
        captured_at: datetime | None,
        price_opportunity_config: PriceOpportunityConfig | None,
        control_change_allowed: bool,
    ) -> tuple[CanonicalPipelineRun, PipelineStageTimings]:
        total_started = perf_counter()
        snapshot = planning_input or _bootstrap_snapshot(captured_at)
        run_id = snapshot.run_id
        snapshot_id = snapshot.snapshot_id

        stage_started = perf_counter()
        opportunities = self._opportunity_engine.detect(
            snapshot,
            price_config=price_opportunity_config,
        )
        opportunity_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        candidate_derivation = None
        derivation_status = "not_available"
        derivation_reason: str | None = "required_inputs_missing"
        if (
            snapshot.current_storage_states
            and snapshot.pv_energy_timeline is not None
            and snapshot.household_load_forecast is not None
        ):
            try:
                candidate_derivation = (
                    self._candidate_engine.derive_storage_requirements(
                        snapshot
                    )
                )
            except CandidateInputError as exc:
                derivation_status = "blocked"
                derivation_reason = str(exc)
            else:
                if candidate_derivation.planning_gaps:
                    derivation_status = "ready_with_gaps"
                    derivation_reason = "pv_forecast_gap"
                else:
                    derivation_status = "ready"
                    derivation_reason = None
        path = EnergyPath(
            run_id=run_id,
            snapshot_id=snapshot_id,
            path_id=_id("energy-path", f"{snapshot_id}|baseline"),
            family="reserve_first",
        )
        candidate = Candidate(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_id=_id("candidate", path.path_id),
            energy_path_id=path.path_id,
            family=path.family,
        )
        delegated_candidates: list[Candidate] = []
        delegated_paths: list[EnergyPath] = []
        delegated_outcomes: list[DelegatedStorageCandidateOutcome] = []
        if candidate_derivation is not None:
            balances_by_id = {
                balance.balance_id: balance
                for balance in candidate_derivation.balances
            }
            for requirement in candidate_derivation.requirements:
                balance = balances_by_id.get(requirement.projected_balance_id)
                if balance is None:
                    continue
                delegated_set = construct_pv_charge_only_candidate(
                    snapshot=snapshot,
                    balance=balance,
                    requirement=requirement,
                )
                if not delegated_set.candidates:
                    continue
                simulated = simulate_pv_charge_only_outcomes(delegated_set)
                delegated_candidates.extend(
                    item
                    for item in delegated_set.candidates
                    if item.candidate_id
                    in {
                        outcome.candidate_id
                        for outcome in simulated.outcomes
                    }
                )
                accepted_path_ids = {
                    item.energy_path_id
                    for item in delegated_candidates
                }
                delegated_paths.extend(
                    item
                    for item in delegated_set.energy_paths
                    if item.path_id in accepted_path_ids
                )
                delegated_outcomes.extend(
                    simulated.outcomes
                )

        candidate_set = CandidateSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_set_id=_id("candidate-set", opportunities.opportunity_set_id),
            candidates=(candidate, *delegated_candidates),
            energy_paths=(path, *delegated_paths),
            projected_balances=(
                candidate_derivation.balances
                if candidate_derivation is not None
                else ()
            ),
            storage_requirements=(
                candidate_derivation.requirements
                if candidate_derivation is not None
                else ()
            ),
            planning_gaps=(
                candidate_derivation.planning_gaps
                if candidate_derivation is not None
                else ()
            ),
            pv_forecast_assumption_set=(
                derive_pv_forecast_basis_assumptions(snapshot)
            ),
            derivation_status=derivation_status,
            derivation_reason=derivation_reason,
        )
        has_evaluated_alternatives = bool(delegated_outcomes)
        outcomes = CandidateOutcomeSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_set_id=candidate_set.candidate_set_id,
            outcome_set_id=_id("outcome-set", candidate_set.candidate_set_id),
            candidate_ids=(
                tuple(item.candidate_id for item in delegated_outcomes)
                if has_evaluated_alternatives
                else (candidate.candidate_id,)
            ),
            outcomes=tuple(delegated_outcomes),
        )
        candidate_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        winning_outcome = (
            min(
                delegated_outcomes,
                key=lambda item: (
                    item.grid_storage_contribution_wh,
                    -item.pv_storage_contribution_wh,
                    item.conversion_losses_wh,
                    -item.confidence,
                    -item.recoverability,
                    item.charge_window_starts_at,
                    item.candidate_id,
                ),
            )
            if has_evaluated_alternatives
            else None
        )
        winning_candidate = (
            next(
                item
                for item in candidate_set.candidates
                if winning_outcome is not None
                and item.candidate_id == winning_outcome.candidate_id
            )
            if winning_outcome is not None
            else candidate
        )
        winning_path = next(
            item
            for item in candidate_set.energy_paths
            if item.path_id == winning_candidate.energy_path_id
        )
        requirement_satisfied = (
            winning_outcome.requirement_satisfied
            if winning_outcome is not None
            else False
        )
        evaluation = EvaluationRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            evaluation_id=_id("evaluation", outcomes.outcome_set_id),
            candidate_set_id=candidate_set.candidate_set_id,
            winning_candidate_id=(
                winning_candidate.candidate_id
            ),
            winning_energy_path_id=(
                winning_path.path_id
            ),
            reason=(
                (
                    "pv_charge_only satisfies the storage requirement using PV-only energy"
                    if requirement_satisfied
                    else "pv_charge_only maximizes storage progress using PV-only energy"
                )
                if has_evaluated_alternatives
                else "no actionable candidate with a calculated outcome"
            ),
            status=(
                "winner_selected"
                if has_evaluated_alternatives
                else "fallback_active"
            ),
            evaluated_candidate_ids=tuple(
                item.candidate_id for item in candidate_set.candidates
            ),
            decisive_step=(
                (
                    "hard_constraint:storage_requirement_satisfied"
                    if requirement_satisfied
                    else "objective:maximize_storage_progress_without_grid"
                )
                if has_evaluated_alternatives
                else "fallback:no_actionable_candidate"
            ),
        )
        evaluation_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        observer_plans: list[ObserverExecutionPlan] = []
        for execution_scope_id in sorted(
            {segment.execution_scope_id for segment in winning_path.segments}
        ):
            path_segments = tuple(
                segment
                for segment in winning_path.segments
                if segment.execution_scope_id == execution_scope_id
            )
            valid_from = min(segment.starts_at for segment in path_segments)
            valid_until = max(segment.ends_at for segment in path_segments)
            planned_primitives = {
                segment.primitive for segment in path_segments
            }
            planned_primitive = next(iter(planned_primitives))
            if len(planned_primitives) != 1:
                raise ValueError(
                    "observer execution plan must contain one primitive"
                )
            mode_evidence = snapshot.storage_mode_capability_evidence
            matching_vendor_modes = (
                tuple(
                    mapping.vendor_mode
                    for mapping in mode_evidence.mappings
                    if planned_primitive in mapping.primitives
                )
                if mode_evidence is not None
                else ()
            )
            plan_vendor_mode = (
                matching_vendor_modes[0]
                if len(matching_vendor_modes) == 1
                else None
            )
            lifecycle_base = (
                "scheduled"
                if snapshot.captured_at < valid_from
                else (
                    "expired"
                    if snapshot.captured_at >= valid_until
                    else "due"
                )
            )
            lifecycle_status = (
                lifecycle_base
                if control_change_allowed
                else f"{lifecycle_base}_observer_only"
            )
            plan_id = _id(
                "execution-plan",
                f"{evaluation.evaluation_id}|{winning_path.path_id}|{execution_scope_id}",
            )
            observer_plans.append(
                ObserverExecutionPlan(
                    plan_id=plan_id,
                    evaluation_id=evaluation.evaluation_id,
                    winning_candidate_id=winning_candidate.candidate_id,
                    winning_energy_path_id=winning_path.path_id,
                    execution_scope_id=execution_scope_id,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    planned_primitive=planned_primitive,
                    planned_vendor_mode=plan_vendor_mode,
                    lifecycle_status=lifecycle_status,
                    observer_only=not control_change_allowed,
                    segments=tuple(
                        ObserverExecutionPlanSegment(
                            segment_id=_id(
                                "execution-plan-segment",
                                f"{plan_id}|{segment.segment_id}",
                            ),
                            source_path_segment_id=segment.segment_id,
                            order=index,
                            starts_at=segment.starts_at,
                            ends_at=segment.ends_at,
                            primitive=segment.primitive,
                            capability_id=segment.capability_id,
                            purpose=segment.purpose,
                            evidence_ids=segment.evidence_ids,
                            requested_power_w=segment.requested_power_w,
                            charge_source_policy=segment.charge_source_policy,
                        )
                        for index, segment in enumerate(path_segments, start=1)
                    ),
                )
            )
        has_due_storage_segment = any(
            segment.starts_at <= snapshot.captured_at < segment.ends_at
            for plan in observer_plans
            for segment in plan.segments
        )
        if not has_due_storage_segment:
            storage_state = next(iter(snapshot.current_storage_states), None)
            capability_set = snapshot.capability_snapshot_set
            baseline_primitive = (
                ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                if snapshot.household_planning_regime is not None
                and snapshot.household_planning_regime.regime
                == "self_consumption_first"
                else ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
            )
            baseline_capability = (
                next(
                    (
                        capability
                        for capability in capability_set.capabilities
                        if storage_state is not None
                        and capability.capability_id == storage_state.capability_id
                        and capability.execution_scope_id
                        == storage_state.execution_scope_id
                        and baseline_primitive in capability.supported_primitives
                    ),
                    None,
                )
                if capability_set is not None
                else None
            )
            future_start = min(
                (
                    segment.starts_at
                    for plan in observer_plans
                    for segment in plan.segments
                    if segment.starts_at > snapshot.captured_at
                ),
                default=None,
            )
            baseline_until = future_start or snapshot.horizon_end or (
                snapshot.captured_at + timedelta(minutes=15)
            )
            if (
                storage_state is not None
                and baseline_capability is not None
                and baseline_until > snapshot.captured_at
                and winning_candidate.candidate_id is not None
            ):
                mode_evidence = snapshot.storage_mode_capability_evidence
                matching_modes = (
                    tuple(
                        mapping.vendor_mode
                        for mapping in mode_evidence.mappings
                        if baseline_primitive in mapping.primitives
                    )
                    if mode_evidence is not None
                    else ()
                )
                plan_vendor_mode = (
                    matching_modes[0] if len(matching_modes) == 1 else None
                )
                plan_id = _id(
                    "execution-plan",
                    f"{evaluation.evaluation_id}|{winning_path.path_id}|"
                    f"{storage_state.execution_scope_id}|baseline-discharge",
                )
                segment_id = _id(
                    "execution-plan-segment",
                    f"{plan_id}|{snapshot.captured_at.isoformat()}|"
                    f"{baseline_until.isoformat()}",
                )
                observer_plans.append(
                    ObserverExecutionPlan(
                        plan_id=plan_id,
                        evaluation_id=evaluation.evaluation_id,
                        winning_candidate_id=winning_candidate.candidate_id,
                        winning_energy_path_id=winning_path.path_id,
                        execution_scope_id=storage_state.execution_scope_id,
                        valid_from=snapshot.captured_at,
                        valid_until=baseline_until,
                        planned_primitive=baseline_primitive,
                        planned_vendor_mode=plan_vendor_mode,
                        lifecycle_status=(
                            "due"
                            if control_change_allowed
                            else "due_observer_only"
                        ),
                        observer_only=not control_change_allowed,
                        segments=(
                            ObserverExecutionPlanSegment(
                                segment_id=segment_id,
                                source_path_segment_id=(
                                    "canonical-baseline-discharge"
                                ),
                                order=1,
                                starts_at=snapshot.captured_at,
                                ends_at=baseline_until,
                                primitive=baseline_primitive,
                                capability_id=baseline_capability.capability_id,
                                purpose=(
                                    "Apply the active household planning regime "
                                    "outside a selected PV charge window"
                                ),
                                evidence_ids=(
                                    baseline_capability.capability_id,
                                    *(
                                        (
                                            snapshot.household_planning_regime.regime_id,
                                        )
                                        if snapshot.household_planning_regime is not None
                                        else ()
                                    ),
                                ),
                                requested_power_w=None,
                                charge_source_policy=None,
                            ),
                        ),
                    )
                )
        execution_plan_set = ExecutionPlanSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            plan_set_id=_id("plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
            plan_ids=tuple(plan.plan_id for plan in observer_plans),
            plans=tuple(observer_plans),
        )
        execution_plan_builder_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        execution_record = ExecutionRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            execution_record_id=_id("execution", execution_plan_set.plan_set_id),
            plan_set_id=execution_plan_set.plan_set_id,
            status=(
                "fallback_active"
                if not has_evaluated_alternatives and observer_plans
                else (
                    "live_plan_ready"
                    if control_change_allowed
                    else "observer_only_plan_ready"
                )
                if observer_plans
                else "no_due_segment"
            ),
            reason=(
                "safe baseline mode active without an actionable calculated plan"
                if not has_evaluated_alternatives and observer_plans
                else (
                    "winning path approved for live execution"
                    if control_change_allowed
                    else "winning path preserved as observer-only execution plan"
                )
                if observer_plans
                else "bootstrap baseline contains no controllable segments"
            ),
        )
        execution_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        due_segment = next(
            (
                segment
                for plan in execution_plan_set.plans
                for segment in plan.segments
                if segment.starts_at <= snapshot.captured_at < segment.ends_at
            ),
            None,
        )
        mode_evidence = snapshot.storage_mode_capability_evidence
        mode_provenance = snapshot.storage_mode_control_provenance
        planned_vendor_mode: str | None = None
        mapping_status = "not_assessed"
        blockers: list[str] = []
        if due_segment is not None and mode_evidence is not None:
            matching_modes = tuple(
                mapping.vendor_mode
                for mapping in mode_evidence.mappings
                if due_segment.primitive in mapping.primitives
            )
            if len(matching_modes) == 1:
                planned_vendor_mode = matching_modes[0]
                mapping_status = "validated"
            else:
                mapping_status = "unavailable"
                blockers.append("primitive_vendor_mapping_unavailable")
            if (
                mode_evidence.current_vendor_mode
                in mode_evidence.excluded_dynamic_vendor_modes
            ):
                blockers.insert(0, "current_vendor_mode_excluded")
            calibration = snapshot.bms_calibration_evidence
            if calibration is not None and calibration.active:
                blockers.insert(0, "bms_soc_calibration_active")
            if mode_provenance is None or (
                mode_provenance.status == "unverified"
                and not control_change_allowed
            ):
                blockers.append("manual_override_provenance_unverified")
            elif mode_provenance.manual_override_active:
                blockers.append("manual_override_active")
            if not control_change_allowed:
                blockers.append("observer_only_authority")
        request_ready = (
            due_segment is not None
            and mapping_status == "validated"
            and blockers in (["observer_only_authority"], [])
        )
        primitive_request_id = (
            _id(
                "primitive-request",
                (
                    f"{execution_record.execution_record_id}|"
                    f"{due_segment.segment_id}"
                ),
            )
            if request_ready and due_segment is not None
            else None
        )
        primitive_boundary = ExecutionPrimitiveBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            request_id=primitive_request_id,
            execution_record_id=execution_record.execution_record_id,
            status=(
                (
                    "request_ready"
                    if control_change_allowed
                    else "observer_request_ready"
                )
                if request_ready
                else (
                    "dry_run_blocked"
                    if due_segment is not None and mode_evidence is not None
                    else "not_emitted"
                )
            ),
            planned_primitive=(
                due_segment.primitive if due_segment is not None else None
            ),
            mapping_status=mapping_status,
            source_entity_id=(
                mode_evidence.source_entity_id
                if mode_evidence is not None
                else None
            ),
            current_vendor_mode=(
                mode_evidence.current_vendor_mode
                if mode_evidence is not None
                else None
            ),
            planned_vendor_mode=planned_vendor_mode,
            mapping_method_version=(
                mode_evidence.method_version
                if mode_evidence is not None
                else None
            ),
            blockers=tuple(blockers),
        )
        execution_primitive_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        translation_ready = (
            primitive_boundary.status in {
                "observer_request_ready",
                "request_ready",
            }
            and primitive_boundary.request_id is not None
            and primitive_boundary.planned_vendor_mode is not None
        )
        adapter_translation_id = (
            _id(
                "adapter-translation",
                (
                    f"{primitive_boundary.request_id}|"
                    f"{primitive_boundary.planned_vendor_mode}|"
                    f"{primitive_boundary.mapping_method_version}"
                ),
            )
            if translation_ready
            else None
        )
        adapter_boundary = DeviceAdapterBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            translation_id=adapter_translation_id,
            primitive_request_id=(
                primitive_boundary.request_id
                if translation_ready
                else None
            ),
            status=(
                (
                    "translation_ready"
                    if control_change_allowed
                    else "observer_translation_ready"
                )
                if translation_ready
                else "not_invoked"
            ),
        )
        device_adapter_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        dispatch_ready = (
            adapter_boundary.status in {
                "observer_translation_ready",
                "translation_ready",
            }
            and adapter_boundary.translation_id is not None
            and primitive_boundary.source_entity_id is not None
            and primitive_boundary.planned_vendor_mode is not None
        )
        dispatch_intent_id = (
            _id(
                "dispatch-intent",
                (
                    f"{adapter_boundary.translation_id}|"
                    f"{primitive_boundary.source_entity_id}|"
                    f"{primitive_boundary.planned_vendor_mode}"
                ),
            )
            if dispatch_ready
            else None
        )
        vendor_result = VendorBoundaryResult(
            run_id=run_id,
            snapshot_id=snapshot_id,
            command_id=None,
            adapter_translation_id=(
                adapter_boundary.translation_id
                if dispatch_ready
                else None
            ),
            status=(
                (
                    "dispatch_ready"
                    if control_change_allowed
                    else "observer_dispatch_ready"
                )
                if dispatch_ready
                else "not_dispatched"
            ),
            dispatch_intent_id=dispatch_intent_id,
            target_entity_id=(
                primitive_boundary.source_entity_id
                if dispatch_ready
                else None
            ),
            planned_vendor_mode=(
                primitive_boundary.planned_vendor_mode
                if dispatch_ready
                else None
            ),
        )
        vendor_result_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        run = CanonicalPipelineRun(
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
        )
        timings = PipelineStageTimings(
            opportunity_engine_ms=opportunity_engine_ms,
            candidate_engine_ms=candidate_engine_ms,
            evaluation_engine_ms=evaluation_engine_ms,
            execution_plan_builder_ms=execution_plan_builder_ms,
            execution_engine_ms=execution_engine_ms,
            execution_primitive_ms=execution_primitive_ms,
            device_adapter_ms=device_adapter_ms,
            vendor_result_ms=vendor_result_ms,
            canonical_total_ms=round((perf_counter() - total_started) * 1000.0, 3),
        )
        return run, timings
