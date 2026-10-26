"""Structural limits for reusing a completed owner's passive historical remainder."""

from datetime import datetime

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.daily_charge_assignment import DailyChargeAssignment


def is_reset_household_route(plan: ExecutionPlan) -> bool:
    return plan.winning_candidate_id.startswith("completed-route:") and all(
        s.purpose == "completed-day-household"
        and s.main_assignment_id is None
        and s.retained_execution_origin is None
        and s.requested_power_w is None
        and s.primitive in {Primitive.BALANCE_BIDIRECTIONAL, Primitive.BALANCE_DISCHARGE_ONLY}
        for s in plan.segments
    )


def passive_remainder_available(
    plan: ExecutionPlan,
    owner: DailyChargeAssignment,
    at: datetime,
) -> bool:
    if (
        plan.plan_id != owner.route_plan_id
        or owner.completed_at is None
        or plan.execution_scope_id != owner.execution_scope_id
        or not plan.valid_from <= at < min(plan.valid_until, owner.ends_at)
    ):
        return False
    end = min(plan.valid_until, owner.ends_at)
    cursor = at
    for part in plan.segments:
        if part.ends_at <= at or part.starts_at >= end:
            continue
        if max(at, part.starts_at) != cursor:
            return False
        cursor = min(end, part.ends_at)
        if part.main_assignment_id == owner.assignment_id:
            continue  # Its proved completed charge is released, never resurrected.
        if (
            part.main_assignment_id is not None
            or part.retained_execution_origin is not None
            or part.requested_power_w is not None
            or part.energy_profile_id is not None
            or part.purpose.startswith(("supplemental:", "reserve:", "market:", "market-day:"))
            or part.primitive
            not in {
                Primitive.BALANCE_BIDIRECTIONAL,
                Primitive.BALANCE_DISCHARGE_ONLY,
                Primitive.STANDBY,
            }
            or (
                part.primitive is Primitive.BALANCE_BIDIRECTIONAL
                and part.charge_source_policy is not ChargeSourcePolicy.PV_ONLY
            )
        ):
            return False
    return cursor == end
