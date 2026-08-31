"""Immutable Execution Plan records defined by ADR-016 and ADR-033."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import SocConstraint
from picot.domain.execution_primitive import ExecutionPrimitive


class ExecutionPlanLifecycle(StrEnum):
    """Lifecycle states for immutable Execution Plan revisions."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExecutionPlanSegment:
    """One vendor-independent segment copied from a Winning Energy Path."""

    segment_id: str
    source_path_segment_id: str
    order: int
    starts_at: datetime
    ends_at: datetime
    primitive: ExecutionPrimitive
    capability_id: str
    purpose: str
    evidence_ids: tuple[str, ...]
    requested_power_w: float | None = None
    soc_constraint: SocConstraint | None = None
    energy_profile_id: str | None = None
    charge_source_policy: ChargeSourcePolicy | None = None

    def __post_init__(self) -> None:
        for text_value, label in (
            (self.segment_id, "Execution segment ID"),
            (self.source_path_segment_id, "Source Path Segment ID"),
            (self.capability_id, "Capability ID"),
            (self.purpose, "Purpose"),
        ):
            if not text_value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.order < 1:
            raise ValueError("Execution segment order must be at least 1.")
        for time_value, label in (
            (self.starts_at, "Execution segment start"),
            (self.ends_at, "Execution segment end"),
        ):
            if time_value.tzinfo is None or time_value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Execution segment must end after it starts.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Execution segment evidence IDs must not be empty.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Execution segment evidence IDs must be unique.")
        if self.energy_profile_id is not None and not self.energy_profile_id.strip():
            raise ValueError("Energy profile ID must not be empty when provided.")
        supports_charge_source_policy = self.primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.BALANCE_CHARGE_ONLY,
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        }
        if not supports_charge_source_policy and self.charge_source_policy is not None:
            raise ValueError(
                "Charge source policy is only valid for charging Execution segments."
            )


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """One immutable scope-specific plan produced from a Winning Energy Path."""

    plan_id: str
    schema_version: int
    revision: int
    created_at: datetime
    valid_from: datetime
    valid_until: datetime
    snapshot_id: str
    strategy_version: int
    evaluation_id: str
    winning_candidate_id: str
    winning_energy_path_id: str
    execution_scope_id: str
    mapping_version: int
    lifecycle: ExecutionPlanLifecycle
    fallback_policy_id: str
    segments: tuple[ExecutionPlanSegment, ...]

    def __post_init__(self) -> None:
        for text_value, label in (
            (self.plan_id, "Execution Plan ID"),
            (self.snapshot_id, "Snapshot ID"),
            (self.evaluation_id, "Evaluation ID"),
            (self.winning_candidate_id, "Winning Candidate ID"),
            (self.winning_energy_path_id, "Winning Energy Path ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.fallback_policy_id, "Fallback policy ID"),
        ):
            if not text_value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.schema_version < 1:
            raise ValueError("Execution Plan schema version must be at least 1.")
        if self.revision < 1:
            raise ValueError("Execution Plan revision must be at least 1.")
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if self.mapping_version < 1:
            raise ValueError("Capability mapping version must be at least 1.")
        for time_value, label in (
            (self.created_at, "Execution Plan creation time"),
            (self.valid_from, "Execution Plan valid-from time"),
            (self.valid_until, "Execution Plan valid-until time"),
        ):
            if time_value.tzinfo is None or time_value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware.")
        if self.valid_until <= self.valid_from:
            raise ValueError("Execution Plan validity must end after it starts.")
        if self.created_at > self.valid_until:
            raise ValueError("Execution Plan creation time may not exceed valid-until.")
        segment_ids = [segment.segment_id for segment in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Each Execution Plan Segment ID may appear only once.")
        orders = [segment.order for segment in self.segments]
        if orders != list(range(1, len(self.segments) + 1)):
            raise ValueError("Execution segment order must be contiguous and start at 1.")
        if any(
            segment.starts_at < self.valid_from or segment.ends_at > self.valid_until
            for segment in self.segments
        ):
            raise ValueError("Every Execution segment must remain within plan validity.")


@dataclass(frozen=True, slots=True)
class ExecutionPlanSet:
    """Atomic collection of scope-specific Execution Plans for one winner."""

    plan_set_id: str
    schema_version: int
    snapshot_id: str
    strategy_version: int
    evaluation_id: str
    winning_candidate_id: str
    winning_energy_path_id: str
    created_at: datetime
    plans: tuple[ExecutionPlan, ...]
    implementation_version: str

    def __post_init__(self) -> None:
        for text_value, label in (
            (self.plan_set_id, "Execution Plan Set ID"),
            (self.snapshot_id, "Snapshot ID"),
            (self.evaluation_id, "Evaluation ID"),
            (self.winning_candidate_id, "Winning Candidate ID"),
            (self.winning_energy_path_id, "Winning Energy Path ID"),
            (self.implementation_version, "Implementation version"),
        ):
            if not text_value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.schema_version < 1:
            raise ValueError("Execution Plan Set schema version must be at least 1.")
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Execution Plan Set creation time must be timezone-aware.")
        plan_ids = [plan.plan_id for plan in self.plans]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("Each Execution Plan ID may appear only once.")
        scopes = [plan.execution_scope_id for plan in self.plans]
        if scopes != sorted(scopes) or len(scopes) != len(set(scopes)):
            raise ValueError("Execution Plans must be unique and ordered by scope.")
        if any(plan.snapshot_id != self.snapshot_id for plan in self.plans):
            raise ValueError("Every Execution Plan must reference the Plan Set snapshot.")
        if any(plan.strategy_version != self.strategy_version for plan in self.plans):
            raise ValueError("Every Execution Plan must use the Plan Set strategy version.")
        if any(plan.evaluation_id != self.evaluation_id for plan in self.plans):
            raise ValueError("Every Execution Plan must reference the Evaluation Record.")
        if any(
            plan.winning_candidate_id != self.winning_candidate_id for plan in self.plans
        ):
            raise ValueError("Every Execution Plan must reference the winning Candidate.")
        if any(
            plan.winning_energy_path_id != self.winning_energy_path_id
            for plan in self.plans
        ):
            raise ValueError("Every Execution Plan must reference the winning Energy Path.")
