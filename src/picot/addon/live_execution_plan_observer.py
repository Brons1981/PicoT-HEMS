"""Observer-only live ADR-033 ExecutionPlanSet construction.

This module performs the deterministic planner-to-plan conversion only. It does
not validate, schedule, execute, translate, or dispatch any plan segment.
"""

from __future__ import annotations

from datetime import datetime

from picot.domain.evaluation import EvaluationOutcomeStatus
from picot.domain.execution_plan import ExecutionPlanSet
from picot.planner.adr037_pipeline import ADR037PlanningResult
from picot.planner.execution_plan_builder import ExecutionPlanBuilder

FALLBACK_POLICY_ID = "execution-fallback:hold-and-replan:v1"

_builder = ExecutionPlanBuilder()


def observe_execution_plan_set(
    planning_result: ADR037PlanningResult | None,
    *,
    created_at: datetime,
) -> tuple[ExecutionPlanSet | None, dict[str, object]]:
    """Construct the ADR-033 plan set without granting execution authority."""

    base: dict[str, object] = {
        "execution_plan_set_available": False,
        "execution_plan_set_id": None,
        "execution_plan_count": 0,
        "execution_fallback_policy_id": FALLBACK_POLICY_ID,
        "execution_plan_construction_status": "planning_result_unavailable",
    }
    if planning_result is None:
        return None, base

    evaluation = planning_result.evaluation
    if evaluation.status is not EvaluationOutcomeStatus.WINNER_SELECTED:
        base["execution_plan_construction_status"] = "no_winner_selected"
        return None, base

    plan_set = _builder.build(
        evaluation,
        created_at=created_at,
        fallback_policy_id=FALLBACK_POLICY_ID,
    )
    fields = {
        **base,
        "execution_plan_set_available": True,
        "execution_plan_set_id": plan_set.plan_set_id,
        "execution_plan_count": len(plan_set.plans),
        "execution_plan_construction_status": "constructed",
    }
    return plan_set, fields
