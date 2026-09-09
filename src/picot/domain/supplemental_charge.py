"""Explicit supplemental charge ownership (ADR-037.10)."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class SupplementalChargeAssignment:
    assignment_id: str
    next_assignment_id: str
    execution_scope_id: str
    target_soc: float
    starts_at: datetime
    ends_at: datetime
    required_by: datetime
    plan_id: str = ""
    segment_ids: tuple[str, ...] = ()
    completed_at: datetime | None = None
    completion_evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not all((self.assignment_id, self.next_assignment_id, self.execution_scope_id)):
            raise ValueError("supplemental goal requires explicit ownership")
        if not isfinite(self.target_soc) or not 0 < self.target_soc <= 1:
            raise ValueError("supplemental target must be a physical SOC")
        if any(t.utcoffset() is None for t in (self.starts_at, self.ends_at, self.required_by)):
            raise ValueError("supplemental boundaries must be aware")
        if not self.starts_at < self.ends_at <= self.required_by:
            raise ValueError("supplemental charge must finish before required energy time")
        if bool(self.plan_id) != bool(self.segment_ids) or len(set(self.segment_ids)) != len(
            self.segment_ids
        ):
            raise ValueError("supplemental execution binding must be complete")
        if (self.completed_at is None) != (self.completion_evidence_id is None):
            raise ValueError("supplemental completion requires evidence")
        if self.completed_at is not None and (
            self.completed_at.utcoffset() is None
            or not self.starts_at <= self.completed_at <= self.ends_at
            or not self.completion_evidence_id
        ):
            raise ValueError("supplemental completion must belong to its window")
