"""Single canonical PicoT pipeline composed around the sole MEP planner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import CanonicalPipelineRun, PlanningInputSnapshot
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.mep_canonical_pipeline import build_mep_canonical_run
from picot.v2.opportunity_engine import OpportunityEngine, PriceOpportunityConfig
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def _id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _bootstrap_snapshot(captured_at: datetime | None = None) -> PlanningInputSnapshot:
    now = captured_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    run_seed = f"{__version__}|{now.isoformat()}|{ARCHITECTURE_BASELINE_COMMIT}"
    run_id = _id("run", run_seed)
    return PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=_id("snapshot", run_id),
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
    """Run the sole MEP planner through the canonical pipeline exactly once."""

    def __init__(
        self,
        *,
        market_daily_planner_runtime: MarketDailyPlannerRuntime,
        opportunity_engine: OpportunityEngine | None = None,
        commitment_store: ActivePlanCommitmentStore | None = None,
        plan_switching_margin_eur: float = 0.05,
    ) -> None:
        if plan_switching_margin_eur < 0.0:
            raise ValueError("plan switching margin must be non-negative")
        self._opportunity_engine = opportunity_engine or OpportunityEngine()
        self._market_daily_planner_runtime = market_daily_planner_runtime
        self._commitment_store = commitment_store
        self._plan_switching_margin_eur = plan_switching_margin_eur

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
        stage_started = perf_counter()
        opportunities = self._opportunity_engine.detect(
            snapshot,
            price_config=price_opportunity_config,
        )
        opportunity_engine_ms = round((perf_counter() - stage_started) * 1000.0, 3)
        run, timings, _ = build_mep_canonical_run(
            snapshot=snapshot,
            opportunities=opportunities,
            planner_runtime=self._market_daily_planner_runtime,
            commitment_store=self._commitment_store,
            control_change_allowed=control_change_allowed,
            switching_margin_eur=self._plan_switching_margin_eur,
        )
        return run, PipelineStageTimings(
            opportunity_engine_ms=opportunity_engine_ms,
            candidate_engine_ms=timings.candidate_engine_ms,
            evaluation_engine_ms=timings.evaluation_engine_ms,
            execution_plan_builder_ms=timings.execution_plan_builder_ms,
            execution_engine_ms=timings.execution_engine_ms,
            execution_primitive_ms=timings.execution_primitive_ms,
            device_adapter_ms=timings.device_adapter_ms,
            vendor_result_ms=timings.vendor_result_ms,
            canonical_total_ms=round((perf_counter() - total_started) * 1000.0, 3),
        )
