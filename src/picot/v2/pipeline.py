"""Minimal end-to-end PicoT v2 canonical pipeline.

Canonical v2 pipeline implementation; diagnostic timing is layered around this path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.candidate_engine import CandidateEngine, CandidateInputError
from picot.v2.contracts import (
    Candidate,
    CandidateOutcomeSet,
    CandidateSet,
    CanonicalPipelineRun,
    DeviceAdapterBoundary,
    EnergyPath,
    EnergyPathSegment,
    EvaluationRecord,
    ExecutionPlan,
    ExecutionPlanSegment,
    ExecutionPlanSet,
    ExecutionPrimitiveBoundary,
    ExecutionRecord,
    PlanningInputSnapshot,
    VendorBoundaryResult,
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


def _first_storage_segment(
    *,
    snapshot: PlanningInputSnapshot,
    opportunities: object,
    candidate_derivation: object,
) -> EnergyPathSegment | None:
    requirements = getattr(candidate_derivation, "requirements", ())
    if not requirements or getattr(candidate_derivation, "planning_gaps", ()):
        return None
    storage = snapshot.current_storage_states[0]
    maximum_power_w = storage.maximum_charge_power_w
    if maximum_power_w is None:
        return None
    low_windows = tuple(
        item
        for item in getattr(opportunities, "opportunities", ())
        if item.kind == "LOWEST_PRICE_WINDOW"
        and item.ends_at > snapshot.captured_at
    )
    if not low_windows:
        return None
    window = min(
        low_windows,
        key=lambda item: (item.starts_at, item.ends_at, item.opportunity_id),
    )
    starts_at = max(snapshot.captured_at, window.starts_at)
    ends_at = window.ends_at
    if starts_at >= ends_at:
        return None
    required_energy_wh = requirements[0].reserve_contribution_wh
    if required_energy_wh <= 0.0:
        return None
    duration_hours = (ends_at - starts_at).total_seconds() / 3600.0
    requested_power_w = min(
        maximum_power_w,
        required_energy_wh / duration_hours,
    )
    segment_id = _id(
        "path-segment",
        (
            f"{snapshot.snapshot_id}|{storage.execution_scope_id}|"
            f"{starts_at.isoformat()}|{ends_at.isoformat()}|"
            f"{requested_power_w}"
        ),
    )
    return EnergyPathSegment(
        segment_id=segment_id,
        execution_scope_id=storage.execution_scope_id,
        capability_id=storage.capability_id,
        starts_at=starts_at,
        ends_at=ends_at,
        primitive="CHARGE_AT_POWER",
        requested_power_w=requested_power_w,
        opportunity_ids=(window.opportunity_id,),
        evidence_ids=tuple(
            dict.fromkeys(
                (
                    *requirements[0].evidence_ids,
                    *(
                        reference.evidence_id
                        for reference in window.evidence
                    ),
                )
            )
        ),
    )


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
    ) -> CanonicalPipelineRun:
        run, _ = self._execute(
            planning_input=planning_input,
            captured_at=captured_at,
            price_opportunity_config=price_opportunity_config,
        )
        return run

    def run_timed(
        self,
        *,
        planning_input: PlanningInputSnapshot | None = None,
        captured_at: datetime | None = None,
        price_opportunity_config: PriceOpportunityConfig | None = None,
    ) -> tuple[CanonicalPipelineRun, PipelineStageTimings]:
        """Execute the canonical route and return passive stage timings."""
        return self._execute(
            planning_input=planning_input,
            captured_at=captured_at,
            price_opportunity_config=price_opportunity_config,
        )

    def _execute(
        self,
        *,
        planning_input: PlanningInputSnapshot | None,
        captured_at: datetime | None,
        price_opportunity_config: PriceOpportunityConfig | None,
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
        storage_segment = (
            _first_storage_segment(
                snapshot=snapshot,
                opportunities=opportunities,
                candidate_derivation=candidate_derivation,
            )
            if candidate_derivation is not None
            else None
        )
        segments = (storage_segment,) if storage_segment is not None else ()
        path = EnergyPath(
            run_id=run_id,
            snapshot_id=snapshot_id,
            path_id=_id(
                "energy-path",
                f"{snapshot_id}|{'storage-charge' if segments else 'baseline'}",
            ),
            family="cost_first" if segments else "reserve_first",
            segment_ids=tuple(segment.segment_id for segment in segments),
            segments=segments,
        )
        candidate = Candidate(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_id=_id("candidate", path.path_id),
            energy_path_id=path.path_id,
            family=path.family,
        )
        candidate_set = CandidateSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_set_id=_id("candidate-set", opportunities.opportunity_set_id),
            candidates=(candidate,),
            energy_paths=(path,),
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
        outcomes = CandidateOutcomeSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_set_id=candidate_set.candidate_set_id,
            outcome_set_id=_id("outcome-set", candidate_set.candidate_set_id),
            candidate_ids=(candidate.candidate_id,),
        )
        candidate_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        evaluation = EvaluationRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            evaluation_id=_id("evaluation", outcomes.outcome_set_id),
            candidate_set_id=candidate_set.candidate_set_id,
            winning_candidate_id=candidate.candidate_id,
            winning_energy_path_id=path.path_id,
            reason="only technically valid bootstrap baseline candidate",
        )
        evaluation_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        plans = ()
        if path.segments:
            plan_id = _id(
                "execution-plan",
                f"{evaluation.evaluation_id}|{path.path_id}",
            )
            plan_segments = tuple(
                ExecutionPlanSegment(
                    segment_id=_id(
                        "execution-segment",
                        f"{plan_id}|{segment.segment_id}",
                    ),
                    source_path_segment_id=segment.segment_id,
                    execution_scope_id=segment.execution_scope_id,
                    capability_id=segment.capability_id,
                    starts_at=segment.starts_at,
                    ends_at=segment.ends_at,
                    primitive=segment.primitive,
                    requested_power_w=segment.requested_power_w,
                    evidence_ids=segment.evidence_ids,
                )
                for segment in path.segments
            )
            plans = (
                ExecutionPlan(
                    plan_id=plan_id,
                    execution_scope_id=path.segments[0].execution_scope_id,
                    valid_from=min(
                        segment.starts_at for segment in path.segments
                    ),
                    valid_until=max(
                        segment.ends_at for segment in path.segments
                    ),
                    segments=plan_segments,
                ),
            )
        execution_plan_set = ExecutionPlanSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            plan_set_id=_id("plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
            plan_ids=tuple(plan.plan_id for plan in plans),
            plans=plans,
        )
        execution_plan_builder_ms = round((perf_counter() - stage_started) * 1000.0, 3)

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
        request_id = (
            _id(
                "execution-request",
                (
                    f"{execution_plan_set.plan_set_id}|"
                    f"{due_segment.segment_id}|"
                    f"{snapshot.captured_at.isoformat()}"
                ),
            )
            if due_segment is not None
            else None
        )
        execution_record = ExecutionRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            execution_record_id=_id("execution", execution_plan_set.plan_set_id),
            plan_set_id=execution_plan_set.plan_set_id,
            status="request_emitted" if request_id else "no_due_segment",
            reason=(
                "due segment passed observer-only execution validation"
                if request_id
                else "winning path contains no due controllable segment"
            ),
        )
        execution_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        primitive_boundary = ExecutionPrimitiveBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            request_id=request_id,
            execution_record_id=execution_record.execution_record_id,
            status="emitted" if request_id else "not_emitted",
        )
        execution_primitive_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        adapter_boundary = DeviceAdapterBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            translation_id=None,
            primitive_request_id=None,
            status="not_invoked",
        )
        device_adapter_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        vendor_result = VendorBoundaryResult(
            run_id=run_id,
            snapshot_id=snapshot_id,
            command_id=None,
            adapter_translation_id=None,
            status="not_dispatched",
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
