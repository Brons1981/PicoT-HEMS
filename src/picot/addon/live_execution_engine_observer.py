"""Observer-only live ExecutionEngine composition for recovery step 3.

This module resolves ADR-046 fallback policy references, invokes the existing
vendor-independent ExecutionEngine, and exposes evidence only. It does not
translate or dispatch any ExecutionPrimitiveRequest.
"""

from __future__ import annotations

from datetime import datetime

from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.execution_plan import ExecutionPlanSet
from picot.execution.execution_engine import ExecutionEngine
from picot.execution.fallback_policy_registry import (
    HOLD_AND_REPLAN_POLICY_ID,
    ExecutionFallbackPolicyRegistry,
)

_engine = ExecutionEngine()
_registry = ExecutionFallbackPolicyRegistry()


def observe_execution_engine(
    plan_set: ExecutionPlanSet | None,
    capabilities: CapabilitySnapshotSet,
    *,
    now: datetime,
) -> dict[str, object]:
    """Resolve fallback references and evaluate due segments without dispatch."""

    base: dict[str, object] = {
        "execution_engine_observed": False,
        "execution_engine_status": "plan_set_unavailable",
        "execution_fallback_policy_resolved": False,
        "execution_request_count": 0,
        "execution_record_count": 0,
        "execution_approved_count": 0,
        "execution_replan_required_count": 0,
        "execution_rejected_count": 0,
        "execution_cancelled_count": 0,
    }
    if plan_set is None:
        return base

    # ADR-046 requires policy availability to be proven before execution may
    # progress. Empty baseline plan sets carry no per-plan reference, but their
    # construction input is still the canonical policy and is resolved here.
    policy_ids = {plan.fallback_policy_id for plan in plan_set.plans}
    if not policy_ids:
        policy_ids = {HOLD_AND_REPLAN_POLICY_ID}
    try:
        for policy_id in policy_ids:
            _registry.resolve(policy_id)
    except ValueError as exc:
        return {
            **base,
            "execution_engine_status": "fallback_policy_unresolved",
            "execution_engine_error": str(exc),
        }

    try:
        result = _engine.execute_due(plan_set, capabilities, now=now)
    except ValueError as exc:
        return {
            **base,
            "execution_fallback_policy_resolved": True,
            "execution_engine_status": "atomic_input_rejected",
            "execution_engine_error": str(exc),
        }

    counts = {
        "approved": 0,
        "replan_required": 0,
        "rejected": 0,
        "cancelled": 0,
    }
    for record in result.records:
        key = record.outcome.value
        if key in counts:
            counts[key] += 1

    return {
        **base,
        "execution_engine_observed": True,
        "execution_engine_status": "evaluated",
        "execution_fallback_policy_resolved": True,
        "execution_request_count": len(result.requests),
        "execution_record_count": len(result.records),
        "execution_approved_count": counts["approved"],
        "execution_replan_required_count": counts["replan_required"],
        "execution_rejected_count": counts["rejected"],
        "execution_cancelled_count": counts["cancelled"],
    }
