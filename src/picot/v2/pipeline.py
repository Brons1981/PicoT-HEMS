"""Minimal end-to-end PicoT v2 canonical pipeline.

Canonical v2 pipeline implementation; diagnostic timing is layered around this path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from picot.planner.delegated_storage_evaluation_engine import (
    DelegatedStorageEvaluationEngine,
)
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.active_plan_candidate import construct_active_plan_candidate
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
    complete_storage_path_with_baseline,
    construct_pv_charge_only_candidate,
)
from picot.v2.delegated_storage_outcomes import (
    simulate_pv_charge_only_outcomes,
)
from picot.v2.opportunity_engine import (
    LOWEST_PRICE_WINDOW,
    NEGATIVE_PRICE_WINDOW,
    OpportunityEngine,
    PriceOpportunityConfig,
)
from picot.v2.pv_forecast_assumptions import (
    derive_pv_forecast_basis_assumptions,
)


def _id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _average_price_for_window(
    snapshot: PlanningInputSnapshot,
    starts_at: datetime,
    ends_at: datetime,
) -> float:
    """Return the duration-weighted quarter-price for one executable window."""

    window_seconds = (ends_at - starts_at).total_seconds()
    priced_seconds = 0.0
    weighted_price = 0.0
    for point in snapshot.price_points:
        overlap_start = max(starts_at, point.starts_at)
        overlap_end = min(ends_at, point.ends_at)
        overlap_seconds = max(
            0.0,
            (overlap_end - overlap_start).total_seconds(),
        )
        priced_seconds += overlap_seconds
        weighted_price += point.value_eur_per_kwh * overlap_seconds
    if window_seconds <= 0.0 or priced_seconds + 1e-6 < window_seconds:
        return float("inf")
    return weighted_price / priced_seconds


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
                incumbent = construct_active_plan_candidate(
                    snapshot,
                    requirement,
                )
                if incumbent is not None:
                    incumbent_candidate, incumbent_path, incumbent_outcome = incumbent
                    delegated_candidates.append(incumbent_candidate)
                    delegated_paths.append(incumbent_path)
                    delegated_outcomes.append(incumbent_outcome)
                preferred_price_windows = tuple(
                    (item.starts_at, item.ends_at)
                    for item in sorted(
                        (
                            opportunity
                            for opportunity in opportunities.opportunities
                            if opportunity.kind
                            in {
                                NEGATIVE_PRICE_WINDOW,
                                LOWEST_PRICE_WINDOW,
                            }
                            and opportunity.ends_at > snapshot.captured_at
                            and opportunity.starts_at < requirement.required_by
                        ),
                        key=lambda opportunity: (
                            0
                            if opportunity.kind == NEGATIVE_PRICE_WINDOW
                            else 1,
                            opportunity.metrics.average_price_eur_per_kwh,
                            opportunity.starts_at,
                            opportunity.opportunity_id,
                        ),
                    )
                )
                delegated_set = construct_pv_charge_only_candidate(
                    snapshot=snapshot,
                    balance=balance,
                    requirement=requirement,
                    preferred_price_windows=preferred_price_windows,
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

        path = complete_storage_path_with_baseline(snapshot, path)
        delegated_paths = [
            complete_storage_path_with_baseline(snapshot, item)
            for item in delegated_paths
        ]
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
        storage_capabilities_by_id = {
            capability.capability_id: capability
            for capability in (
                snapshot.capability_snapshot_set.capabilities
                if snapshot.capability_snapshot_set is not None
                else ()
            )
        }
        balances_by_id = {
            balance.balance_id: balance
            for balance in (
                candidate_derivation.balances
                if candidate_derivation is not None
                else ()
            )
        }
        requirements_by_id = {
            requirement.requirement_id: requirement
            for requirement in (
                candidate_derivation.requirements
                if candidate_derivation is not None
                else ()
            )
        }

        def reserve_is_safe(
            outcome: DelegatedStorageCandidateOutcome,
        ) -> bool:
            requirement = requirements_by_id.get(outcome.storage_requirement_id)
            if requirement is None:
                return False
            storage = next(
                (
                    item
                    for item in snapshot.current_storage_states
                    if item.storage_state_id == requirement.storage_state_id
                ),
                None,
            )
            if storage is None:
                return False
            capability = storage_capabilities_by_id.get(storage.capability_id)
            minimum_soc = capability.minimum_soc if capability is not None else None
            if minimum_soc is None:
                return False
            balance = balances_by_id.get(requirement.projected_balance_id)
            if balance is None:
                return False
            energy_at_next_charge = next(
                (
                    interval.current_usable_storage_energy_wh
                    for interval in balance.intervals
                    if interval.starts_at == requirement.required_by
                ),
                None,
            )
            return (
                energy_at_next_charge is not None
                and energy_at_next_charge + 1e-6
                >= minimum_soc * storage.usable_capacity_wh
            )

        def is_micro_charge(
            outcome: DelegatedStorageCandidateOutcome,
        ) -> bool:
            requirement = requirements_by_id.get(outcome.storage_requirement_id)
            if requirement is None:
                return False
            storage = next(
                (
                    item
                    for item in snapshot.current_storage_states
                    if item.storage_state_id == requirement.storage_state_id
                ),
                None,
            )
            contribution = (
                outcome.pv_storage_contribution_wh
                + outcome.grid_storage_contribution_wh
            )
            return (
                storage is not None
                and contribution <= storage.usable_capacity_wh * 0.01 + 1e-6
            )

        delegated_evaluation_engine = DelegatedStorageEvaluationEngine()
        incumbent_candidate_ids = (
            delegated_evaluation_engine.incumbent_candidate_ids(
                snapshot=snapshot,
                candidate_set=candidate_set,
                candidate_ids=tuple(
                    item.candidate_id for item in delegated_outcomes
                ),
            )
        )
        actionable_outcomes = tuple(
            outcome
            for outcome in delegated_outcomes
            if outcome.confidence > 0.0
            and (
                outcome.candidate_id in incumbent_candidate_ids
                or
                outcome.pv_storage_contribution_wh
                + outcome.grid_storage_contribution_wh
                > 1e-6
            )
            and (
                outcome.candidate_id in incumbent_candidate_ids
                or not (is_micro_charge(outcome) and reserve_is_safe(outcome))
            )
        )
        has_actionable_alternatives = bool(actionable_outcomes)
        storage_states_by_id = {
            state.storage_state_id: state
            for state in snapshot.current_storage_states
        }
        storage_requirement_already_satisfied = (
            candidate_derivation is not None
            and derivation_status == "ready"
            and all(
                requirement.storage_state_id in storage_states_by_id
                and storage_states_by_id[
                    requirement.storage_state_id
                ].current_soc
                >= requirement.required_soc
                for requirement in candidate_derivation.requirements
            )
        )
        micro_charge_suppressed = (
            bool(delegated_outcomes)
            and not has_actionable_alternatives
            and all(
                is_micro_charge(outcome) and reserve_is_safe(outcome)
                for outcome in delegated_outcomes
            )
        )
        storage_requirement_operationally_satisfied = (
            storage_requirement_already_satisfied or micro_charge_suppressed
        )
        has_valid_plan = (
            has_actionable_alternatives
            or storage_requirement_operationally_satisfied
        )
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
        delegated_evaluation = delegated_evaluation_engine.evaluate(
            snapshot=snapshot,
            candidate_set=candidate_set,
            actionable_outcomes=actionable_outcomes,
        )
        winning_outcome = delegated_evaluation.winning_outcome
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
                "active plan commitment retained while storage acquisition continues"
                if delegated_evaluation.incumbent_retained
                else (
                    "pv_charge_only satisfies the storage requirement using PV-only energy"
                    if requirement_satisfied
                    else "pv_charge_only maximizes storage progress using PV-only energy"
                )
                if has_actionable_alternatives
                else (
                    (
                        "remaining storage gap is at or below one percent; "
                        "reserve remains sufficient until the next charge opportunity"
                        if micro_charge_suppressed
                        else "storage requirement already satisfied; "
                        "no additional charge action required"
                    )
                    if storage_requirement_operationally_satisfied
                    else "no actionable candidate with a calculated outcome"
                )
            ),
            status=(
                "winner_selected"
                if has_valid_plan
                else "fallback_active"
            ),
            evaluated_candidate_ids=tuple(
                item.candidate_id for item in candidate_set.candidates
            ),
            decisive_step=(
                delegated_evaluation.decisive_step
                or (
                    "hard_constraint:storage_requirement_satisfied"
                    if requirement_satisfied
                    else "objective:maximize_storage_progress_without_grid"
                )
                if has_actionable_alternatives
                else (
                    (
                        "stability:micro_charge_suppressed_with_safe_reserve"
                        if micro_charge_suppressed
                        else "hard_constraint:storage_requirement_already_satisfied"
                    )
                    if storage_requirement_operationally_satisfied
                    else "fallback:no_actionable_candidate"
                )
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
            applicable_segment = next(
                (
                    segment
                    for segment in path_segments
                    if segment.starts_at
                    <= snapshot.captured_at
                    < segment.ends_at
                ),
                path_segments[0],
            )
            planned_primitive = applicable_segment.primitive
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
            if delegated_evaluation.incumbent_retained:
                active_commitment = next(
                    (
                        item
                        for item in snapshot.active_plan_commitments
                        if item.execution_scope_id == execution_scope_id
                    ),
                    None,
                )
                if active_commitment is not None:
                    plan_id = active_commitment.plan_id
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
                if not has_valid_plan and observer_plans
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
                if not has_valid_plan and observer_plans
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
