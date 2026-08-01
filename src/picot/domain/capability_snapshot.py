"""Immutable logical capability snapshots defined by ADR-030."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.household_state import Phase


class CapabilityAvailability(StrEnum):
    """Current runtime availability of one logical capability."""

    AVAILABLE = "available"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CapabilityHealth(StrEnum):
    """Current validated health of one logical capability."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class EnergyFlowDirection(StrEnum):
    """Energy-flow directions supported by one logical capability."""

    CHARGE = "charge"
    DISCHARGE = "discharge"
    BIDIRECTIONAL = "bidirectional"
    CONSUME = "consume"
    PRODUCE = "produce"


@dataclass(frozen=True, slots=True)
class LogicalCapabilitySnapshot:
    """Atomic logical capability state available to the Planner."""

    capability_id: str
    execution_scope_id: str
    supported_primitives: tuple[ExecutionPrimitive, ...]
    availability: CapabilityAvailability
    health: CapabilityHealth
    fresh_at: datetime
    confidence: float
    source_mapping_id: str
    adapter_contract_version: str
    flow_directions: tuple[EnergyFlowDirection, ...] = ()
    minimum_power_w: float | None = None
    maximum_power_w: float | None = None
    minimum_soc: float | None = None
    maximum_soc: float | None = None
    phases: tuple[Phase, ...] = ()
    minimum_on_seconds: int | None = None
    minimum_off_seconds: int | None = None
    power_step_w: float | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.capability_id, "Capability ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.source_mapping_id, "Source mapping ID"),
            (self.adapter_contract_version, "Adapter contract version"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.fresh_at.tzinfo is None or self.fresh_at.utcoffset() is None:
            raise ValueError("Capability freshness time must be timezone-aware.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Capability confidence must be between 0.0 and 1.0.")
        self._require_unique(self.supported_primitives, "supported primitives")
        self._require_unique(self.flow_directions, "flow directions")
        self._require_unique(self.phases, "phases")
        if self.minimum_power_w is not None and self.minimum_power_w < 0:
            raise ValueError("Minimum power must not be negative.")
        if self.maximum_power_w is not None and self.maximum_power_w <= 0:
            raise ValueError("Maximum power must be greater than zero.")
        if (
            self.minimum_power_w is not None
            and self.maximum_power_w is not None
            and self.minimum_power_w > self.maximum_power_w
        ):
            raise ValueError("Minimum power must not exceed maximum power.")
        for value, label in (
            (self.minimum_soc, "Minimum SoC"),
            (self.maximum_soc, "Maximum SoC"),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be between 0.0 and 1.0.")
        if (
            self.minimum_soc is not None
            and self.maximum_soc is not None
            and self.minimum_soc > self.maximum_soc
        ):
            raise ValueError("Minimum SoC must not exceed maximum SoC.")
        for value, label in (
            (self.minimum_on_seconds, "Minimum on-time"),
            (self.minimum_off_seconds, "Minimum off-time"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must not be negative.")
        if self.power_step_w is not None and self.power_step_w <= 0:
            raise ValueError("Power step must be greater than zero.")

    @staticmethod
    def _require_unique(values: tuple[object, ...], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"Capability {label} must be unique.")


@dataclass(frozen=True, slots=True)
class CapabilitySnapshotSet:
    """Atomic capability view linked to one Planning Input Snapshot."""

    snapshot_id: str
    mapping_version: int
    captured_at: datetime
    capabilities: tuple[LogicalCapabilitySnapshot, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Capability Snapshot Set snapshot ID must not be empty.")
        if self.mapping_version < 1:
            raise ValueError("Capability mapping version must be at least 1.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("Capability capture time must be timezone-aware.")
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("Each logical capability ID may appear only once.")
        if any(item.fresh_at > self.captured_at for item in self.capabilities):
            raise ValueError("Capability freshness time must not be in the future.")
