"""Explicit user intent to rebuild an open daily route, never a fabricated deficit."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyChargeRevisionReason


@dataclass(frozen=True, slots=True)
class DailyPlanRecalculationRequest:
    request_id: str
    requested_at: datetime
    assignment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.request_id.strip() or self.requested_at.utcoffset() is None:
            raise ValueError("daily recalculation requires explicit identity and time")
        if not self.assignment_ids or any(not item.strip() for item in self.assignment_ids):
            raise ValueError("daily recalculation requires remaining daily owners")
        if len(set(self.assignment_ids)) != len(self.assignment_ids):
            raise ValueError("daily recalculation cannot duplicate owners")


@dataclass(frozen=True, slots=True)
class DailyMainRecalculationTrigger:
    assignment_id: str
    route_plan_id: str
    revision: int
    active_plan_id: str
    snapshot_id: str
    assessed_at: datetime
    target_wh: float
    request: DailyPlanRecalculationRequest

    @property
    def revision_reason(self) -> DailyChargeRevisionReason:
        return DailyChargeRevisionReason.MANUAL_RECALCULATION

    def validate(self, owner: DailyChargeAssignment, snapshot_id: str, at: datetime) -> None:
        if (
            (owner.assignment_id, owner.route_plan_id, owner.revision)
            != (self.assignment_id, self.route_plan_id, self.revision)
            or owner.completed_at is not None or not self.route_plan_id
            or not self.active_plan_id or (snapshot_id, at) != (self.snapshot_id, self.assessed_at)
            or at >= owner.ends_at or self.request.requested_at > at
            or owner.assignment_id not in self.request.assignment_ids
            or not isfinite(self.target_wh) or self.target_wh <= 0
        ):
            raise ValueError("manual recalculation must match the current open route and input")
