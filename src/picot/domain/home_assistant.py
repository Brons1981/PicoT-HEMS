"""Immutable Home Assistant adapter records defined by ADR-035."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.execution_primitive import ExecutionPrimitive


class HomeAssistantDispatchMode(StrEnum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class HomeAssistantDispatchStatus(StrEnum):
    DRY_RUN_ONLY = "dry_run_only"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HomeAssistantCommandMapping:
    mapping_id: str
    mapping_version: int
    capability_id: str
    execution_scope_id: str
    primitive: ExecutionPrimitive
    domain: str
    service: str
    entity_id: str
    value_key: str
    fixed_value: str | None = None
    scale_factor: float = 1.0
    minimum_value: float | None = None
    maximum_value: float | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        for value, label in (
            (self.mapping_id, "Mapping ID"),
            (self.capability_id, "Capability ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.domain, "Home Assistant domain"),
            (self.service, "Home Assistant service"),
            (self.entity_id, "Home Assistant entity ID"),
            (self.value_key, "Service data value key"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.mapping_version < 1:
            raise ValueError("Mapping version must be at least 1.")
        if self.fixed_value is not None and not self.fixed_value.strip():
            raise ValueError("Fixed mapping value must not be empty when provided.")
        if self.scale_factor <= 0:
            raise ValueError("Scale factor must be greater than zero.")
        if (
            self.minimum_value is not None
            and self.maximum_value is not None
            and self.minimum_value > self.maximum_value
        ):
            raise ValueError("Minimum mapping value may not exceed maximum value.")


@dataclass(frozen=True, slots=True)
class HomeAssistantServiceCall:
    command_id: str
    source_request_id: str
    plan_set_id: str
    plan_id: str
    segment_id: str
    execution_scope_id: str
    capability_id: str
    mapping_id: str
    mapping_version: int
    domain: str
    service: str
    target: tuple[tuple[str, str], ...]
    service_data: tuple[tuple[str, str | float], ...]
    created_at: datetime
    dispatch_mode: HomeAssistantDispatchMode
    implementation_version: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.command_id, "Command ID"),
            (self.source_request_id, "Source request ID"),
            (self.plan_set_id, "Plan Set ID"),
            (self.plan_id, "Plan ID"),
            (self.segment_id, "Segment ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.capability_id, "Capability ID"),
            (self.mapping_id, "Mapping ID"),
            (self.domain, "Home Assistant domain"),
            (self.service, "Home Assistant service"),
            (self.implementation_version, "Implementation version"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.mapping_version < 1:
            raise ValueError("Mapping version must be at least 1.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Service call creation time must be timezone-aware.")
        if not self.target or any(
            not key.strip() or not value.strip() for key, value in self.target
        ):
            raise ValueError("Home Assistant target must contain non-empty values.")
        if not self.service_data or any(
            not key.strip() for key, _ in self.service_data
        ):
            raise ValueError("Home Assistant service data must contain non-empty keys.")
        if any(
            isinstance(value, str) and not value.strip()
            for _, value in self.service_data
        ):
            raise ValueError("String service data values must not be empty.")


@dataclass(frozen=True, slots=True)
class HomeAssistantDispatchResult:
    command_id: str
    dispatch_mode: HomeAssistantDispatchMode
    status: HomeAssistantDispatchStatus
    attempted_at: datetime
    response_status: int | None = None
    error_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("Command ID must not be empty.")
        if self.attempted_at.tzinfo is None or self.attempted_at.utcoffset() is None:
            raise ValueError("Dispatch attempt time must be timezone-aware.")
        if self.response_status is not None and self.response_status < 100:
            raise ValueError("Response status must be a valid HTTP-style status code.")
        if self.error_reason is not None and not self.error_reason.strip():
            raise ValueError("Error reason must not be empty when provided.")
        if self.status in {
            HomeAssistantDispatchStatus.REJECTED,
            HomeAssistantDispatchStatus.FAILED,
        } and self.error_reason is None:
            raise ValueError("Rejected or failed dispatch requires an error reason.")
