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
    EvaluationRecord,
    ExecutionPlanSet,
    ExecutionPrimitiveBoundary,
    ExecutionRecord,
    PlanningInputSnapshot,
    VendorBoundaryResult,
)
from picot.v2.opportunity_engine import OpportunityEngine, PriceOpportunityConfig


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
        execution_plan_set = ExecutionPlanSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            plan_set_id=_id("plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
        )
        execution_plan_builder_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        execution_record = ExecutionRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            execution_record_id=_id("execution", execution_plan_set.plan_set_id),
            plan_set_id=execution_plan_set.plan_set_id,
            status="no_due_segment",
            reason="bootstrap baseline contains no controllable segments",
        )
        execution_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)

        stage_started = perf_counter()
        primitive_boundary = ExecutionPrimitiveBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            request_id=None,
            execution_record_id=execution_record.execution_record_id,
            status="not_emitted",
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
