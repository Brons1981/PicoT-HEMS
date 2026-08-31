"""Policy-free projection of canonical ADR-033 plans to the live v2 DTO."""

from __future__ import annotations

from datetime import datetime

from picot.architecture_ownership import architecture_ownership
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_plan import ExecutionPlanSet as DomainExecutionPlanSet
from picot.v2.contracts import (
    ExecutionPlanSet,
    ObserverExecutionPlan,
    ObserverExecutionPlanSegment,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("execution_plan_projection", __name__)


def project_execution_plan_set(
    canonical: DomainExecutionPlanSet,
    *,
    run_id: str,
    captured_at: datetime,
    observer_only: bool,
    admitted_plan_ids_by_scope: dict[str, str] | None = None,
) -> ExecutionPlanSet:
    """Copy canonical plan content and apply only Store-admitted plan identities."""

    admitted_ids = admitted_plan_ids_by_scope or {}
    plans = tuple(
        _project_plan(
            plan,
            captured_at=captured_at,
            observer_only=observer_only,
            admitted_plan_id=admitted_ids.get(plan.execution_scope_id, plan.plan_id),
        )
        for plan in canonical.plans
    )
    return ExecutionPlanSet(
        run_id=run_id,
        snapshot_id=canonical.snapshot_id,
        plan_set_id=canonical.plan_set_id,
        evaluation_id=canonical.evaluation_id,
        winning_energy_path_id=canonical.winning_energy_path_id,
        plan_ids=tuple(item.plan_id for item in plans),
        plans=plans,
    )


def _project_plan(
    plan: ExecutionPlan,
    *,
    captured_at: datetime,
    observer_only: bool,
    admitted_plan_id: str,
) -> ObserverExecutionPlan:
    # Kept local to this compatibility boundary; no planning policy is applied.
    segments = plan.segments
    due = next(
        (
            item
            for item in segments
            if item.starts_at <= captured_at < item.ends_at
        ),
        segments[0],
    )
    return ObserverExecutionPlan(
        plan_id=admitted_plan_id,
        evaluation_id=plan.evaluation_id,
        winning_candidate_id=plan.winning_candidate_id,
        winning_energy_path_id=plan.winning_energy_path_id,
        execution_scope_id=plan.execution_scope_id,
        valid_from=plan.valid_from,
        valid_until=plan.valid_until,
        planned_primitive=due.primitive,
        planned_vendor_mode=None,
        lifecycle_status=(
            "due"
            if due.starts_at <= captured_at < due.ends_at
            else "scheduled"
        ),
        observer_only=observer_only,
        segments=tuple(
            ObserverExecutionPlanSegment(
                segment_id=item.segment_id,
                source_path_segment_id=item.source_path_segment_id,
                order=item.order,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                primitive=item.primitive,
                capability_id=item.capability_id,
                purpose=item.purpose,
                evidence_ids=item.evidence_ids,
                requested_power_w=item.requested_power_w,
                charge_source_policy=item.charge_source_policy,
                planned_vendor_mode=None,
            )
            for item in segments
        ),
    )
