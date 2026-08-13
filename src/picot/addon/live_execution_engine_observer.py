"""Observer-only ExecutionEngine composition for recovery step 3.

The module resolves ADR-046 fallback policy references, invokes the existing
vendor-independent ExecutionEngine, and applies the ADR-047 authority boundary
before any emitted primitive could progress toward an adapter/dispatch path.

No Device Adapter or dispatch is connected here.
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
    control_authority: str = "unverified",
) -> dict[str, object]:
    """Evaluate due segments without adapter/dispatch authority.

    ADR-047 deliberately forbids guessing control authority. Until the persisted
    provenance component exists and proves ``picot`` ownership, any primitive
    request produced by the engine is suppressed fail-closed at composition.
    Empty plan sets can still be fully evaluated because they emit no primitive.
    """

    base: dict[str, object] = {
        "execution_engine_observed": False,
        "execution_engine_status": "plan_set_unavailable",
        "execution_fallback_policy_resolved": False,
        "execution_control_authority": control_authority,
        "execution_authority_verified": control_authority == "picot",
        "execution_request_count": 0,
        "execution_raw_request_count": 0,
        "execution_record_count": 0,
        "execution_approved_count": 0,
        "execution_replan_required_count": 0,
        "execution_rejected_count": 0,
        "execution_cancelled_count": 0,
        "execution_authority_suppressed_count": 0,
        "execution_adapter_invoked": False,
        "execution_dispatch_attempted": False,
    }
    if plan_set is None:
        return base

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

    raw_request_count = len(result.requests)
    authority_verified = control_authority == "picot"
    suppressed_count = 0 if authority_verified else raw_request_count
    exposed_request_count = raw_request_count if authority_verified else 0
    status = (
        "authority_suppressed"
        if raw_request_count and not authority_verified
        else "evaluated"
    )

    return {
        **base,
        "execution_engine_observed": True,
        "execution_engine_status": status,
        "execution_fallback_policy_resolved": True,
        "execution_authority_verified": authority_verified,
        "execution_request_count": exposed_request_count,
        "execution_raw_request_count": raw_request_count,
        "execution_record_count": len(result.records),
        "execution_approved_count": counts["approved"],
        "execution_replan_required_count": counts["replan_required"],
        "execution_rejected_count": counts["rejected"],
        "execution_cancelled_count": counts["cancelled"],
        "execution_authority_suppressed_count": suppressed_count,
    }
