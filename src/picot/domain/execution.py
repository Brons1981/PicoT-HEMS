"""Immutable Execution Engine records defined by ADR-015 and ADR-016."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.energy_path import SocConstraint
from picot.domain.execution_primitive import ExecutionPrimitive


class CommandValidationOutcome(StrEnum):
    """Deterministic validation outcome for one due execution segment."""

    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REPLAN_REQUIRED = "replan_required"


@dataclass(frozen=True, slots=True)
class ExecutionPrimitiveRequest:
    """Vendor-independent request emitted for a validated plan segment."""

    request_id: str
    plan_set_id: str
    plan_id: str
    plan_revision: int
    segment_id: str
    execution_scope_id: str
    capability_id: str
    primitive: ExecutionPrimitive
    requested_at: datetime
    requested_power_w: float | None = None
    soc_constraint: SocConstraint | None = None
    energy_profile_id: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "Execution request ID"),
            (self.plan_set_id, "Execution Plan Set ID"),
            (self.plan_id, "Execution Plan ID"),
            (self.segment_id, "Execution segment ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.capability_id, "Capability ID"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.plan_revision < 1:
            raise ValueError("Execution request plan revision must be at least 1.")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Execution request time must be timezone-aware.")
        if self.energy_profile_id is not None and not self.energy_profile_id.strip():
            raise ValueError("Energy profile ID must not be empty when provided.")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Validation record for one due Execution Plan Segment."""

    record_id: str
    plan_set_id: str
    plan_id: str
    segment_id: str
    execution_scope_id: str
    capability_id: str
    evaluated_at: datetime
    outcome: CommandValidationOutcome
    reason: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "Execution record ID"),
            (self.plan_set_id, "Execution Plan Set ID"),
            (self.plan_id, "Execution Plan ID"),
            (self.segment_id, "Execution segment ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.capability_id, "Capability ID"),
            (self.reason, "Execution record reason"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Execution evaluation time must be timezone-aware.")
        if self.request_id is not None and not self.request_id.strip():
            raise ValueError("Execution request ID must not be empty when provided.")
        if self.outcome is CommandValidationOutcome.APPROVED and self.request_id is None:
            raise ValueError("Approved execution records require a request ID.")
        if self.outcome is not CommandValidationOutcome.APPROVED and self.request_id is not None:
            raise ValueError("Non-approved execution records may not reference a request.")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Atomic result of one deterministic Execution Engine pass."""

    plan_set_id: str
    evaluated_at: datetime
    requests: tuple[ExecutionPrimitiveRequest, ...]
    records: tuple[ExecutionRecord, ...]
    implementation_version: str

    def __post_init__(self) -> None:
        if not self.plan_set_id.strip():
            raise ValueError("Execution Result Plan Set ID must not be empty.")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("Execution Result evaluation time must be timezone-aware.")
        if not self.implementation_version.strip():
            raise ValueError("Execution implementation version must not be empty.")
        request_ids = [request.request_id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("Each Execution Primitive Request ID may appear only once.")
        record_ids = [record.record_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Each Execution Record ID may appear only once.")
        if any(request.plan_set_id != self.plan_set_id for request in self.requests):
            raise ValueError("Every request must reference the Execution Result Plan Set.")
        if any(record.plan_set_id != self.plan_set_id for record in self.records):
            raise ValueError("Every record must reference the Execution Result Plan Set.")
        approved_request_ids = {
            record.request_id
            for record in self.records
            if record.outcome is CommandValidationOutcome.APPROVED
        }
        if approved_request_ids != set(request_ids):
            raise ValueError("Approved records and emitted requests must match exactly.")
