"""Minimal end-to-end PicoT v2 canonical pipeline.

No optimisation intelligence lives here yet. This module exists only to prove
that the accepted stage boundaries can execute as one route without a side path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
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


def _id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


class CanonicalPipeline:
    """Execute the minimal accepted route exactly once for one immutable run."""

    def run(self, *, captured_at: datetime | None = None) -> CanonicalPipelineRun:
        now = captured_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")

        run_seed = f"{__version__}|{now.isoformat()}|{ARCHITECTURE_BASELINE_COMMIT}"
        run_id = _id("run", run_seed)
        snapshot_id = _id("snapshot", run_id)

        planning_input = PlanningInputSnapshot(
            run_id=run_id,
            snapshot_id=snapshot_id,
            captured_at=now,
            picot_version=__version__,
            architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
            pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
            strategy_id="strategy:no-objectives:v1",
        )

        opportunities = OpportunitySet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            opportunity_set_id=_id("opportunity-set", snapshot_id),
        )

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
        )

        outcomes = CandidateOutcomeSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            candidate_set_id=candidate_set.candidate_set_id,
            outcome_set_id=_id("outcome-set", candidate_set.candidate_set_id),
            candidate_ids=(candidate.candidate_id,),
        )

        evaluation = EvaluationRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            evaluation_id=_id("evaluation", outcomes.outcome_set_id),
            candidate_set_id=candidate_set.candidate_set_id,
            winning_candidate_id=candidate.candidate_id,
            winning_energy_path_id=path.path_id,
            reason="only technically valid bootstrap baseline candidate",
        )

        execution_plan_set = ExecutionPlanSet(
            run_id=run_id,
            snapshot_id=snapshot_id,
            plan_set_id=_id("plan-set", evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            winning_energy_path_id=evaluation.winning_energy_path_id,
        )

        execution_record = ExecutionRecord(
            run_id=run_id,
            snapshot_id=snapshot_id,
            execution_record_id=_id("execution", execution_plan_set.plan_set_id),
            plan_set_id=execution_plan_set.plan_set_id,
            status="no_due_segment",
            reason="bootstrap baseline contains no controllable segments",
        )

        primitive_boundary = ExecutionPrimitiveBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            request_id=None,
            execution_record_id=execution_record.execution_record_id,
            status="not_emitted",
        )

        adapter_boundary = DeviceAdapterBoundary(
            run_id=run_id,
            snapshot_id=snapshot_id,
            translation_id=None,
            primitive_request_id=None,
            status="not_invoked",
        )

        vendor_result = VendorBoundaryResult(
            run_id=run_id,
            snapshot_id=snapshot_id,
            command_id=None,
            adapter_translation_id=None,
            status="not_dispatched",
        )

        return CanonicalPipelineRun(
            planning_input=planning_input,
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
