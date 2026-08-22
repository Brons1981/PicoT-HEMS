"""Minimal end-to-end PicoT v2 canonical pipeline.

Canonical v2 pipeline implementation; diagnostic timing is layered around this path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.delegated_storage_evaluation_engine import (
    DelegatedStorageEvaluationEngine,
)
from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.candidate_engine import CandidateEngine, CandidateInputError
from picot.v2.canonical_reference_observer import (
    METHOD_VERSION as REFERENCE_OBSERVER_METHOD_VERSION,
)
from picot.v2.canonical_reference_observer import CanonicalReferenceObserver
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
    ProjectedHouseholdEnergyBalance,
    PVForecastBasisAssumption,
    ReferenceSimulationSet,
    VendorBoundaryResult,
)
from picot.v2.delegated_storage_candidates import (
    complete_storage_path_with_baseline,
    construct_grid_requirement_candidates,
    construct_pv_charge_only_candidate,
)
from picot.v2.delegated_storage_outcomes import (
    simulate_grid_requirement_outcomes,
    simulate_pv_charge_only_outcomes,
)
from picot.v2.opportunity_engine import OpportunityEngine, PriceOpportunityConfig
from picot.v2.pv_forecast_assumptions import (
    derive_pv_forecast_basis_assumptions,
)
from picot.v2.zendure_mode_capabilities import ZendureModeCapabilityEvidence


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


def _vendor_mode_for_primitive(
    mode_evidence: ZendureModeCapabilityEvidence | None,
    primitive: ExecutionPrimitive,
) -> str | None:
    matches = (
        tuple(
            mapping.vendor_mode
            for mapping in mode_evidence.mappings
            if primitive in mapping.primitives
        )
        if mode_evidence is not None
        else ()
    )
    return matches[0] if len(matches) == 1 else None


def _vendor_mode_for_segment(
    mode_evidence: ZendureModeCapabilityEvidence | None,
    primitive: ExecutionPrimitive,
    source_policy: ChargeSourcePolicy | None,
) -> str | None:
    """Resolve source-aware plan evidence without emitting an adapter request."""

    if mode_evidence is None:
        return None
    if source_policy is not None and source_policy.permits_grid_import:
        grid_matches = tuple(
            mapping.vendor_mode
            for mapping in mode_evidence.mappings
            if mapping.charge_source_semantics == "pv_and_grid"
            and mapping.control_semantics == "delegated"
            and not mapping.requires_proven_power_limits
        )
        return grid_matches[0] if len(grid_matches) == 1 else None
    return _vendor_mode_for_primitive(mode_evidence, primitive)


def _promotable_grid_candidate_id(
    reference: ReferenceSimulationSet,
) -> str | None:
    """Return the uniquely proven grid Candidate; never select on partial evidence."""

    admission = reference.grid_requirement_admission
    decision = reference.grid_requirement_decision
    shadow = reference.grid_requirement_shadow_evaluation
    feasibility = reference.grid_requirement_shadow_execution_feasibility
    financial = reference.financial_comparison
    if (
        admission is None
        or admission.status != "ready"
        or decision is None
        or decision.status != "ready"
        or shadow is None
        or shadow.status != "winner_projected"
        or feasibility is None
        or feasibility.status != "feasible"
        or financial is None
        or financial.status != "ready"
    ):
        return None
    candidate_id = feasibility.candidate_id
    if (
        candidate_id is None
        or candidate_id != shadow.projected_winning_candidate_id
        or not any(
            item.candidate_id == candidate_id and item.status == "admissible"
            for item in admission.assessments
        )
        or not any(
            item.candidate_id == candidate_id
            and item.eligible_for_future_evaluation
            for item in decision.candidates
        )
        or not any(
            item.candidate_id == candidate_id
            and item.candidate_family == "grid_requirement"
            for item in financial.comparisons
        )
    ):
        return None
    return candidate_id


def _balance_for_pv_forecast_basis(
    balance: ProjectedHouseholdEnergyBalance,
    assumption: PVForecastBasisAssumption,
) -> ProjectedHouseholdEnergyBalance:
    """Project one existing household balance onto an explicit PV basis."""

    if assumption.status != "available":
        raise ValueError("PV forecast basis must be available")
    projected = []
    for interval in balance.intervals:
        selected_energy_wh = 0.0
        covered_seconds = 0.0
        for source in assumption.intervals:
            overlap_start = max(interval.starts_at, source.starts_at)
            overlap_end = min(interval.ends_at, source.ends_at)
            overlap_seconds = max(
                0.0,
                (overlap_end - overlap_start).total_seconds(),
            )
            if overlap_seconds <= 0.0:
                continue
            source_seconds = (source.ends_at - source.starts_at).total_seconds()
            selected_energy_wh += (
                source.selected_energy_wh * overlap_seconds / source_seconds
            )
            covered_seconds += overlap_seconds
        interval_seconds = (interval.ends_at - interval.starts_at).total_seconds()
        projected.append(
            replace(
                interval,
                expected_usable_pv_energy_wh=(
                    selected_energy_wh
                    if covered_seconds + 1e-6 >= interval_seconds
                    else interval.expected_usable_pv_energy_wh
                ),
            )
        )
    return replace(balance, intervals=tuple(projected))


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
        observer_only_paths: list[EnergyPath] = []
        delegated_outcomes: list[DelegatedStorageCandidateOutcome] = []
        observer_only_outcomes: list[DelegatedStorageCandidateOutcome] = []
        forecast_assumptions = derive_pv_forecast_basis_assumptions(snapshot)
        lower_assumption = next(
            (
                item
                for item in forecast_assumptions.assumptions
                if item.basis == "lower" and item.status == "available"
            ),
            None,
        )
        if candidate_derivation is not None:
            balances_by_id = {
                balance.balance_id: balance
                for balance in candidate_derivation.balances
            }
            for requirement in candidate_derivation.requirements:
                balance = balances_by_id.get(requirement.projected_balance_id)
                if balance is None:
                    continue
                forecast_basis = "lower" if lower_assumption is not None else "central"
                candidate_balance = (
                    _balance_for_pv_forecast_basis(balance, lower_assumption)
                    if lower_assumption is not None
                    else balance
                )
                delegated_set = construct_pv_charge_only_candidate(
                    snapshot=snapshot,
                    balance=candidate_balance,
                    requirement=requirement,
                    # Price opportunities remain visible evidence. Candidate
                    # coverage is complete and Evaluation compares the real
                    # duration-weighted average price of every feasible window.
                    preferred_price_windows=(),
                    pv_forecast_basis=forecast_basis,
                )
                storage = next(
                    (
                        item
                        for item in snapshot.current_storage_states
                        if item.storage_state_id == requirement.storage_state_id
                    ),
                    None,
                )
                capability = next(
                    (
                        item
                        for item in (
                            snapshot.capability_snapshot_set.capabilities
                            if snapshot.capability_snapshot_set is not None
                            else ()
                        )
                        if storage is not None
                        and item.capability_id == storage.capability_id
                    ),
                    None,
                )
                minimum_reserve_energy_wh = (
                    capability.minimum_soc * storage.usable_capacity_wh
                    if storage is not None
                    and capability is not None
                    and capability.minimum_soc is not None
                    else None
                )
                simulated_outcomes: tuple[DelegatedStorageCandidateOutcome, ...] = ()
                if delegated_set.candidates:
                    simulated = simulate_pv_charge_only_outcomes(
                        delegated_set,
                        minimum_reserve_energy_wh=minimum_reserve_energy_wh,
                    )
                    simulated_outcomes = simulated.outcomes
                    accepted_candidate_ids = {
                        outcome.candidate_id for outcome in simulated_outcomes
                    }
                    accepted_candidates = tuple(
                        item
                        for item in delegated_set.candidates
                        if item.candidate_id in accepted_candidate_ids
                    )
                    accepted_path_ids = {
                        item.energy_path_id for item in accepted_candidates
                    }
                    delegated_candidates.extend(accepted_candidates)
                    delegated_paths.extend(
                        item
                        for item in delegated_set.energy_paths
                        if item.path_id in accepted_path_ids
                    )
                    delegated_outcomes.extend(simulated_outcomes)
                if (
                    not any(item.requirement_satisfied for item in simulated_outcomes)
                    and snapshot.storage_conversion_model is not None
                ):
                    grid_set = construct_grid_requirement_candidates(
                        snapshot=snapshot,
                        balance=candidate_balance,
                        requirement=requirement,
                    )
                    if grid_set.candidates:
                        grid_simulated = simulate_grid_requirement_outcomes(
                            grid_set,
                            charge_efficiency=(
                                snapshot.storage_conversion_model.charge_efficiency
                            ),
                            minimum_reserve_energy_wh=minimum_reserve_energy_wh,
                        )
                        delegated_candidates.extend(grid_set.candidates)
                        observer_only_paths.extend(grid_set.energy_paths)
                        observer_only_outcomes.extend(grid_simulated.outcomes)

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
            energy_paths=(path, *delegated_paths, *observer_only_paths),
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
            pv_forecast_assumption_set=forecast_assumptions,
            derivation_status=derivation_status,
            derivation_reason=derivation_reason,
        )
        reference_outcomes = tuple((*delegated_outcomes, *observer_only_outcomes))
        has_evaluated_alternatives = bool(reference_outcomes)
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
                tuple(item.candidate_id for item in reference_outcomes)
                if has_evaluated_alternatives
                else (candidate.candidate_id,)
            ),
            outcomes=reference_outcomes,
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
                (
                    "scheduled plan commitment retained after current household "
                    "energy-path simulation"
                    if winning_outcome is not None
                    and winning_outcome.charge_window_starts_at > snapshot.captured_at
                    else "active plan commitment retained while storage acquisition "
                    "continues"
                )
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

        try:
            reference_simulations = CanonicalReferenceObserver().observe(
                snapshot=snapshot,
                candidate_set=candidate_set,
                outcomes=outcomes,
                evaluation=evaluation,
            )
        except Exception as exc:  # observer failure may never affect live planning
            reference_simulations = ReferenceSimulationSet(
                run_id=run_id,
                snapshot_id=snapshot_id,
                candidate_set_id=candidate_set.candidate_set_id,
                observations=(),
                method_version=REFERENCE_OBSERVER_METHOD_VERSION,
                global_blockers=(f"observer_failure:{type(exc).__name__}",),
            )

        grid_execution_embargo = False
        promotion_candidate_id = _promotable_grid_candidate_id(reference_simulations)
        promoted_outcome = next(
            (
                item
                for item in observer_only_outcomes
                if item.candidate_id == promotion_candidate_id
                and item.confidence > 0.0
            ),
            None,
        )
        if promoted_outcome is not None:
            promoted_evaluation = delegated_evaluation_engine.evaluate(
                v×m6¶‰žËkºwµç@€€€€€€€€€€‰Ý¥¹¹¥¹}…¹‘¥‘…Ñ•}¥ˆè”¹Ý¥¹¹¥¹}…¹‘¥‘…Ñ•}¥°(€€€€€€€€€€€€€€€€‰Ý¥¹¹¥¹}•¹•Éå}Á…Ñ¡}¥ˆè”¹Ý¥¹¹¥¹}•¹•Éå}Á…Ñ¡}¥°(€€€€€€€€€€€€€€€€‰Ý¥¹¹¥¹}™…µ¥±äˆè€ (€€€€€€€€€€€€€€€€€€€Ý¥¹¹¥¹}…¹‘¥‘…Ñ”¹™…µ¥±ä(€€€€€€€€€€€€€€€€€€€¥˜Ý¥¹¹¥¹}…¹‘¥‘…Ñ”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰•Ù…±Õ…Ñ•‘}…¹‘¥‘…Ñ•}¥‘Ìˆè±¥ÍÐ¡”¹•Ù…±Õ…Ñ•‘}…¹‘¥‘…Ñ•}¥‘Ì¤°(€€€€€€€€€€€€€€€€‰‘•¥Í¥Ù•}ÍÑ•Àˆè”¹‘•¥Í¥Ù•}ÍÑ•À°(€€€€€€€€€€€€€€€€‰É•…Í½¸ˆè”¹É•…Í½¸°(€€€€€€€€€€€ô°(€€€€€€€€¤°(€€€€€€€…É (€€€€€€€€€€€€‰Í•¹Í½È¹Á¥½Ñ}ØÉ}Á¥Á•±¥¹•|ÀÕ}•á•ÕÑ¥½¹}Á±…¹}‰Õ¥±‘•Èˆ°(€€€€€€€€€€€€ (€€€€€€€€€€€€€€€€‰‰±½­•ˆ(€€€€€€€€€€€€€€€¥˜”¹Ý¥¹¹¥¹}…¹‘¥‘…Ñ•}¥¥Ì9½¹”(€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€‰½‰Í•ÉÙ•É}½¹±äˆ(€€€€€€€€€€€€€€€€€€€¥˜•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä(€€€€€€€€€€€€€€€€€€€•±Í”€‰±¥Ù”ˆ(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€¤°(€€€€€€€€€€€‰…Í” (€€€€€€€€€€€€€€€”¹•Ù…±Õ…Ñ¥½¹}¥°(€€€€€€€€€€€€€€€ÁÌ¹Á±…¹}Í•Ñ}¥°(€€€€€€€€€€€€€€€€‰‘•É¥Ù•ˆ°(€€€€€€€€€€€€€€€½‰Í•ÉÙ•É}½¹±äõ•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä°(€€€€€€€€€€€€¤(€€€€€€€€€€€ðì(€€€€€€€€€€€€€€€€‰Á±…¹}½Õ¹Ðˆè±•¸¡ÁÌ¹Á±…¹}¥‘Ì¤°(€€€€€€€€€€€€€€€€‰Á±…¹ÌˆèÁÉ½©•Ñ•‘}Á±…¹Ì°(€€€€€€€€€€€ô°(€€€€€€€€¤°(€€€€€€€…É (€€€€€€€€€€€€‰Í•¹Í½È¹Á¥½Ñ}ØÉ}Á¥Á•±¥¹•|ÀÙ}•á•ÕÑ¥½¹}•¹¥¹”ˆ°(€€€€€€€€€€€•È¹ÍÑ…ÑÕÌ°(€€€€€€€€€€€‰…Í” (€€€€€€€€€€€€€€€ÁÌ¹Á±…¹}Í•Ñ}¥°(€€€€€€€€€€€€€€€•È¹•á•ÕÑ¥½¹}É•½É‘}¥°(€€€€€€€€€€€€€€€€‰‘•É¥Ù•ˆ°(€€€€€€€€€€€€€€€½‰Í•ÉÙ•É}½¹±äõ•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä°(€€€€€€€€€€€€¤(€€€€€€€€€€€ðì‰É•…Í½¸ˆè•È¹É•…Í½¹ô°(€€€€€€€€¤°(€€€€€€€…É (€€€€€€€€€€€€‰Í•¹Í½È¹Á¥½Ñ}ØÉ}Á¥Á•±¥¹•|ÀÝ}•á•ÕÑ¥½¹}ÁÉ¥µ¥Ñ¥Ù”ˆ°(€€€€€€€€€€€Áˆ¹ÍÑ…ÑÕÌ°(€€€€€€€€€€€‰…Í” (€€€€€€€€€€€€€€€•È¹•á•ÕÑ¥½¹}É•½É‘}¥°(€€€€€€€€€€€€€€€Áˆ¹É•ÅÕ•ÍÑ}¥½È€‰¹½¹”ˆ°(€€€€€€€€€€€€€€€€‰¹½Ñ}½¹ÍÕµ•ˆ°(€€€€€€€€€€€€€€€½‰Í•ÉÙ•É}½¹±äõ•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä°(€€€€€€€€€€€€¤(€€€€€€€€€€€ðì(€€€€€€€€€€€€€€€€‰É•ÅÕ•ÍÑ}¥ˆèÁˆ¹É•ÅÕ•ÍÑ}¥°(€€€€€€€€€€€€€€€€‰Á±…¹¹•‘}ÁÉ¥µ¥Ñ¥Ù”ˆè€ (€€€€€€€€€€€€€€€€€€€Áˆ¹Á±…¹¹•‘}ÁÉ¥µ¥Ñ¥Ù”¹Ù…±Õ”(€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹Á±…¹¹•‘}ÁÉ¥µ¥Ñ¥Ù”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰µ…ÁÁ¥¹}ÍÑ…ÑÕÌˆèÁˆ¹µ…ÁÁ¥¹}ÍÑ…ÑÕÌ°(€€€€€€€€€€€€€€€€‰Í½ÕÉ•}•¹Ñ¥Ñå}¥ˆèÁˆ¹Í½ÕÉ•}•¹Ñ¥Ñå}¥°(€€€€€€€€€€€€€€€€‰ÕÉÉ•¹Ñ}Ù•¹‘½É}µ½‘”ˆèÁˆ¹ÕÉÉ•¹Ñ}Ù•¹‘½É}µ½‘”°(€€€€€€€€€€€€€€€€‰Á±…¹¹•‘}Ù•¹‘½É}µ½‘”ˆèÁˆ¹Á±…¹¹•‘}Ù•¹‘½É}µ½‘”°(€€€€€€€€€€€€€€€€‰µ…ÁÁ¥¹}µ•Ñ¡½‘}Ù•ÉÍ¥½¸ˆèÁˆ¹µ…ÁÁ¥¹}µ•Ñ¡½‘}Ù•ÉÍ¥½¸°(€€€€€€€€€€€€€€€€‰‰±½­•ÉÌˆè±¥ÍÐ¡Áˆ¹‰±½­•ÉÌ¤°(€€€€€€€€€€€€€€€€‰¡…É•}Í½ÕÉ•}Á½±¥äˆè€ (€€€€€€€€€€€€€€€€€€€Áˆ¹¡…É•}Í½ÕÉ•}Á½±¥ä¹Ù…±Õ”(€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹¡…É•}Í½ÕÉ•}Á½±¥ä¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰Ù…±¥‘}™É½´ˆè€ (€€€€€€€€€€€€€€€€€€€Áˆ¹Ù…±¥‘}™É½´¹¥Í½™½Éµ…Ð ¤¥˜Áˆ¹Ù…±¥‘}™É½´¥Ì¹½Ð9½¹”•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰Ù…±¥‘}Õ¹Ñ¥°ˆè€ (€€€€€€€€€€€€€€€€€€€Áˆ¹Ù…±¥‘}Õ¹Ñ¥°¹¥Í½™½Éµ…Ð ¤¥˜Áˆ¹Ù…±¥‘}Õ¹Ñ¥°¥Ì¹½Ð9½¹”•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰É•ÅÕ•ÍÑ•‘}Á½Ý•É}ÜˆèÁˆ¹É•ÅÕ•ÍÑ•‘}Á½Ý•É}Ü°(€€€€€€€€€€€€€€€€‰…Á…‰¥±¥Ñå}¥‘Ìˆè±¥ÍÐ¡Áˆ¹…Á…‰¥±¥Ñå}¥‘Ì¤°(€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}¥‘Ìˆè±¥ÍÐ¡Áˆ¹•Ù¥‘•¹•}¥‘Ì¤°(€€€€€€€€€€€€€€€€‰‘•±•…Ñ•‘}½¹ÑÉ½°ˆèÁˆ¹‘•±•…Ñ•‘}½¹ÑÉ½°°(€€€€€€€€€€€€€€€€‰¹½Éµ…±}É•ÍÕ±Ðˆè€ (€€€€€€€€€€€€€€€€€€€€‰!•ÐÉ¥‘±……‘Ù•Éé½•¬¥Ì•É••ìM¹•°½Á±…‘•¸•¸¡•Ð€ˆ(€€€€€€€€€€€€€€€€€€€€‰±……‘Ù•¹ÍÑ•Èé¥©¸Ù…ÍÑ•±•°µ……È‘”…‘…ÁÑ•È¥Ì¹½œ•‰±½­­••É¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹ÍÑ…ÑÕÌ€ôô€‰É¥‘}É•ÅÕ•ÍÑ}É•…‘äˆ(€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€‰”Õ¥ÑÙ½•É‰…É”½Á‘É…¡Ð¥ÌÙ½½É‰•É•¥ìA¥½P­¥©­Ð€ˆ(€€€€€€€€€€€€€€€€€€€€‰¹½œµ•”•¸ÍÑÕÕÉÐ¹¥•ÑÌ¹……Èi•¹‘ÕÉ”¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹ÍÑ…ÑÕÌ€ôô€‰½‰Í•ÉÙ•É}É•ÅÕ•ÍÑ}É•…‘äˆ(€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€‰”Õ¥ÑÙ½•É‰…É”½Á‘É…¡Ð¥ÌÙÉ¥©••Ù•¸Ù½½È€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰……¹ÍÑÕÉ¥¹œÙ…¸i•¹‘ÕÉ”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹ÍÑ…ÑÕÌ€ôô€‰É•ÅÕ•ÍÑ}É•…‘äˆ(€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€‰È¥Ì¹Ô••¸Õ¥ÑÙ½•É‰…É”½Á‘É…¡ÐìA¥½PÍÑÕÕÉÐ€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰¹¥•ÑÌ¹……Èi•¹‘ÕÉ”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹ÍÑ…ÑÕÌ€ôô€‰¹½Ñ}•µ¥ÑÑ•ˆ(€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰”Õ¥ÑÙ½•É‰…É”½Á‘É…¡Ð¥Ì•‰±½­­••ÉìA¥½P€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰ÍÑÕÕÉÐ¹¥•ÑÌ¹……Èi•¹‘ÕÉ”¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜Áˆ¹ÍÑ…ÑÕÌ€ôô€‰‘Éå}ÉÕ¹}‰±½­•ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰µ½‘•}ÁÉ½Ù•¹…¹•}ÍÑ…ÑÕÌˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹ÍÑ…ÑÕÌ(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”€‰Õ¹Ù•É¥™¥•ˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰µ…¹Õ…±}½Ù•ÉÉ¥‘•}…Ñ¥Ù”ˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹µ…¹Õ…±}½Ù•ÉÉ¥‘•}…Ñ¥Ù”(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”…±Í”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰µ½‘•}ÁÉ½Ù•¹…¹•}É•…Í½¸ˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹ÑÉ…¹Í¥Ñ¥½¹}É•…Í½¸(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”€‰¹½}ÁÉ½Ù•¹…¹•}•Ù¥‘•¹”ˆ(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰µ½‘•}½‰Í•ÉÙ•‘}…Ðˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹½‰Í•ÉÙ•‘}…Ð¹¥Í½™½Éµ…Ð ¤(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰±…ÍÑ}Á±…¹¹•É}Ù•¹‘½É}µ½‘”ˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹±…ÍÑ}Á±…¹¹•É}Ù•¹‘½É}µ½‘”(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€€€€€‰±…ÍÑ}Á±…¹¹•É}…ÁÁ±¥•‘}…Ðˆè€ (€€€€€€€€€€€€€€€€€€€À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹±…ÍÑ}Á±…¹¹•É}…ÁÁ±¥•‘}…Ð¹¥Í½™½Éµ…Ð ¤(€€€€€€€€€€€€€€€€€€€¥˜À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€…¹À¹ÍÑ½É…•}µ½‘•}½¹ÑÉ½±}ÁÉ½Ù•¹…¹”¹±…ÍÑ}Á±…¹¹•É}…ÁÁ±¥•‘}…Ð¥Ì¹½Ð9½¹”(€€€€€€€€€€€€€€€€€€€•±Í”9½¹”(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€ô°(€€€€€€€€¤°(€€€€€€€…É (€€€€€€€€€€€€‰Í•¹Í½È¹Á¥½Ñ}ØÉ}Á¥Á•±¥¹•|Àá}‘•Ù¥•}…‘…ÁÑ•Èˆ°(€€€€€€€€€€€…ˆ¹ÍÑ…ÑÕÌ°(€€€€€€€€€€€‰…Í” (€€€€€€€€€€€€€€€Áˆ¹É•ÅÕ•ÍÑ}¥½È€‰¹½¹”ˆ°(€€€€€€€€€€€€€€€…ˆ¹ÑÉ…¹Í±…Ñ¥½¹}¥½È€‰¹½¹”ˆ°(€€€€€€€€€€€€€€€€‰¹½Ñ}½¹ÍÕµ•ˆ°(€€€€€€€€€€€€€€€½‰Í•ÉÙ•É}½¹±äõ•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä°(€€€€€€€€€€€€¤(€€€€€€€€€€€ðì(€€€€€€€€€€€€€€€€‰ÑÉ…¹Í±…Ñ¥½¹}¥ˆè…ˆ¹ÑÉ…¹Í±…Ñ¥½¹}¥°(€€€€€€€€€€€€€€€€‰ÁÉ¥µ¥Ñ¥Ù•}É•ÅÕ•ÍÑ}¥ˆè…ˆ¹ÁÉ¥µ¥Ñ¥Ù•}É•ÅÕ•ÍÑ}¥°(€€€€€€€€€€€€€€€€‰Á±…¹¹•‘}Ù•¹‘½É}µ½‘”ˆèÁˆ¹Á±…¹¹•‘}Ù•¹‘½É}µ½‘”°(€€€€€€€€€€€€€€€€‰¹½Éµ…±}É•ÍÕ±Ðˆè€ (€€€€€€€€€€€€€€€€€€€€‰”½Á‘É…¡Ð¥ÌÙ•ÉÑ……±Ù½½Èi•¹‘ÕÉ”ìA¥½P­¥©­Ð€ˆ(€€€€€€€€€€€€€€€€€€€€‰¹½œµ•”•¸Ù•ÉÍÑÕÕÉÐ¹¥•ÑÌ¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜…ˆ¹ÍÑ…ÑÕÌ€ôô€‰½‰Í•ÉÙ•É}ÑÉ…¹Í±…Ñ¥½¹}É•…‘äˆ(€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€‰”½Á‘É…¡Ð¥ÌÙ•ÉÑ……±•¸‘½½É••Ù•¸……¸‘”€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰i•¹‘ÕÉ”µ­½ÁÁ•±¥¹œ¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜…ˆ¹ÍÑ…ÑÕÌ¥¸ì‰ÑÉ…¹Í±…Ñ¥½¹}É•…‘äˆ°€‰ÑÉ…¹Í±…Ñ•‰ô(€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€‰È¥Ì••¸½Á‘É…¡ÐÙ•ÉÑ……±ì‘”…ÁÁ…É……Ñ­½ÁÁ•±¥¹œ€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€‰¥Ì¹¥•Ð……¹•É½•Á•¸¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€ô°(€€€€€€€€¤°(€€€€€€€…É (€€€€€€€€€€€€‰Í•¹Í½È¹Á¥½Ñ}ØÉ}Á¥Á•±¥¹•|Àå}Ù•¹‘½É}É•ÍÕ±Ðˆ°(€€€€€€€€€€€ÙÈ¹ÍÑ…ÑÕÌ°(€€€€€€€€€€€‰…Í” (€€€€€€€€€€€€€€€…ˆ¹ÑÉ…¹Í±…Ñ¥½¹}¥½È€‰¹½¹”ˆ°(€€€€€€€€€€€€€€€ÙÈ¹½µµ…¹‘}¥½È€‰¹½¹”ˆ°(€€€€€€€€€€€€€€€€‰¹½Ñ}½¹ÍÕµ•ˆ°(€€€€€€€€€€€€€€€½‰Í•ÉÙ•É}½¹±äõ•á•ÕÑ¥½¹}½‰Í•ÉÙ•É}½¹±ä°(€€€€€€€€€€€€¤(€€€€€€€€€€€ðì(€€€€€€€€€€€€€€€€‰‘¥ÍÁ…Ñ¡}¥¹Ñ•¹Ñ}¥ˆèÙÈ¹‘¥ÍÁ…Ñ¡}¥¹Ñ•¹Ñ}¥°(€€€€€€€€€€€€€€€€‰…‘…ÁÑ•É}ÑÉ…¹Í±…Ñ¥½¹}¥ˆèÙÈ¹…‘…ÁÑ•É}ÑÉ…¹Í±…Ñ¥½¹}¥°(€€€€€€€€€€€€€€€€‰Ñ…É•Ñ}•¹Ñ¥Ñå}¥ˆèÙÈ¹Ñ…É•Ñ}•¹Ñ¥Ñå}¥°(€€€€€€€€€€€€€€€€‰Á±…¹¹•‘}Ù•¹‘½É}µ½‘”ˆèÙÈ¹Á±…¹¹•‘}Ù•¹‘½É}µ½‘”°(€€€€€€€€€€€€€€€€‰½µµ…¹‘}¥ˆèÙÈ¹½µµ…¹‘}¥°(€€€€€€€€€€€€€€€€‰½‰Í•ÉÙ•‘}É•ÍÕ±Ñ}¥ˆèÙÈ¹½‰Í•ÉÙ•‘}É•ÍÕ±Ñ}¥°(€€€€€€€€€€€€€€€€‰¹½Éµ…±}É•ÍÕ±Ðˆè€ (€€€€€€€€€€€€€€€€€€€€‰”i•¹‘ÕÉ”µ½Á‘É…¡Ð¥ÌÙ½±±•‘¥œÙ½½É‰•É•¥ìA¥½P€ˆ(€€€€€€€€€€€€€€€€€€€€‰­¥©­Ð¹½œµ•”•¸¡••™Ð¹¥•ÑÌÙ•ÉÍÑÕÕÉ¸ˆ(€€€€€€€€€€€€€€€€€€€¥˜ÙÈ¹ÍÑ…ÑÕÌ€ôô€‰½‰Í•ÉÙ•É}‘¥ÍÁ…Ñ¡}É•…‘äˆ(€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€‰”½Á‘É…¡Ð¥Ì¹……Èi•¹‘ÕÉ”Ù•ÉÍÑÕÕÉ¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€¥˜ÙÈ¹ÍÑ…ÑÕÌ€ôô€‰‘¥ÍÁ…Ñ¡•ˆ(€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰i•¹‘ÕÉ”ÍÑ½¹…°¥¸‘”•Á±…¹‘”µ½‘ÕÌ¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜ÙÈ¹ÍÑ…ÑÕÌ€ôô€‰…±É•…‘å}…Ñ¥Ù”ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€ (€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰A¥½PÝ…¡Ð½À‰•Ù•ÍÑ¥¥¹œÙ…¸‘”Ù½É¥”€ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€‰i•¹‘ÕÉ”µ½Á‘É…¡Ð¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€¥˜ÙÈ¹ÍÑ…ÑÕÌ€ôô€‰…Ý…¥Ñ¥¹}µ½‘•}™••‘‰…¬ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€•±Í”€‰È¥Ì••¸½Á‘É…¡Ð¹……Èi•¹‘ÕÉ”Ù•ÉÍÑÕÕÉ¸ˆ(€€€€€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€ô°(€€€€€€€€¤°(€€€€¤(€€€•±…ÁÍ•‘}µÌ€ôÉ½Õ¹ ¡Á•É™}½Õ¹Ñ•È ¤€´ÍÑ…ÉÑ•¤€¨€ÄÀÀÀ¸À°€Ì¤(€€€É•ÑÕÉ¸AÉ½©•Ñ¥½¸¡…É‘Ìõ…É‘Ì°ÁÉ½©•Ñ¥½¹}µÌõ•±…ÁÍ•‘}µÌ¤(