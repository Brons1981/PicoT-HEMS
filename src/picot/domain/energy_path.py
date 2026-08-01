"""Immutable candidate Energy Path records defined by ADR-030."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.candidate import CandidateFamily
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.household_state import Phase


@dataclass(frozen=True, slots=True)
class SocConstraint:
    """Optional generic SoC bounds attached to one path segment."""

    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.minimum, "Minimum SoC"), (self.maximum, "Maximum SoC")):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be between 0.0 and 1.0.")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum SoC must not exceed maximum SoC.")


@dataclass(frozen=True, slots=True)
class PathSegment:
    """Logical planned behaviour for one execution scope and time interval."""

    segment_id: str
    order: int
    execution_scope_id: str
    starts_at: datetime
    ends_at: datetime
    primitive: ExecutionPrimitive
    capability_id: str
    purpose: str
    evidence_ids: tuple[str, ...]
    requested_power_w: float | None = None
    soc_constraint: SocConstraint | None = None
    energy_profile_id: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.segment_id, "Segment ID"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.capability_id, "Capability ID"),
            (self.purpose, "Purpose"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.order < 1:
            raise ValueError("Segment order must be at least 1.")
        for value, label in ((self.starts_at, "Segment start"), (self.ends_at, "Segment end")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Path segment must end after it starts.")
        if self.requested_power_w is not None and self.requested_power_w <= 0:
            raise ValueError("Requested power must be greater than zero.")
        requires_power = self.primitive in {
            ExecutionPrimitive.CHARGE_AT_POWER,
            ExecutionPrimitive.DISCHARGE_AT_POWER,
        }
        if requires_power and self.requested_power_w is None:
            raise ValueError("Power-based execution primitives require requested power.")
        if not requires_power and self.requested_power_w is not None:
            raise ValueError("Requested power is only valid for power-based primitives.")
        if self.energy_profile_id is not None and not self.energy_profile_id.strip():
            raise ValueError("Energy profile ID must not be empty when provided.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Evidence IDs must not be empty.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Evidence IDs must be unique.")


@dataclass(frozen=True, slots=True)
class PhaseProjection:
    """Projected electrical load for one phase at one state point."""

    phase: Phase
    current_a: float

    def __post_init__(self) -> None:
        if self.current_a < 0:
            raise ValueError("Projected phase current must not be negative.")


@dataclass(frozen=True, slots=True)
class ProjectedEnergyState:
    """One projected household energy state within an Energy Path."""

    at: datetime
    confidence: float
    household_import_w: float | None = None
    household_export_w: float | None = None
    pv_production_w: float | None = None
    household_demand_w: float | None = None
    battery_soc: float | None = None
    ev_energy_wh: float | None = None
    controllable_load_w: float | None = None
    conversion_losses_w: float | None = None
    phase_loads: tuple[PhaseProjection, ...] = ()

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("Projected state time must be timezone-aware.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Projected state confidence must be between 0.0 and 1.0.")
        for value, label in (
            (self.household_import_w, "Household import"),
            (self.household_export_w, "Household export"),
            (self.pv_production_w, "PV production"),
            (self.household_demand_w, "Household demand"),
            (self.ev_energy_wh, "EV energy"),
            (self.controllable_load_w, "Controllable load"),
            (self.conversion_losses_w, "Conversion losses"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must not be negative.")
        if self.battery_soc is not None and not 0.0 <= self.battery_soc <= 1.0:
            raise ValueError("Battery SoC must be between 0.0 and 1.0.")
        phases = [item.phase for item in self.phase_loads]
        if len(phases) != len(set(phases)):
            raise ValueError("Each projected phase may appear only once per state point.")


@dataclass(frozen=True, slots=True)
class EnergyPath:
    """One complete possible household energy scenario over the horizon."""

    path_id: str
    snapshot_id: str
    family: CandidateFamily
    horizon_start: datetime
    horizon_end: datetime
    segments: tuple[PathSegment, ...]
    projected_states: tuple[ProjectedEnergyState, ...]
    opportunity_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    strategy_version: int
    mapping_version: int
    assumptions: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        for value, label in ((self.path_id, "Path ID"), (self.snapshot_id, "Snapshot ID")):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        for value, label in (
            (self.horizon_start, "Horizon start"),
            (self.horizon_end, "Horizon end"),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} must be timezone-aware.")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("Energy Path horizon must end after it starts.")
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if self.mapping_version < 1:
            raise ValueError("Capability mapping version must be at least 1.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Energy Path confidence must be between 0.0 and 1.0.")
        self._require_unique_non_empty(self.opportunity_ids, "opportunity")
        self._require_unique_non_empty(self.constraint_ids, "constraint")
        self._require_unique_non_empty(self.capability_ids, "capability")
        if any(not assumption.strip() for assumption in self.assumptions):
            raise ValueError("Energy Path assumptions must not be empty.")
        self._validate_segments()
        self._validate_projected_states()

    def _validate_segments(self) -> None:
        segment_ids = [segment.segment_id for segment in self.segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Each Path Segment ID may appear only once.")
        orders = [segment.order for segment in self.segments]
        if orders != list(range(1, len(self.segments) + 1)):
            raise ValueError("Path Segment order must be contiguous and start at 1.")
        if any(
            segment.starts_at < self.horizon_start or segment.ends_at > self.horizon_end
            for segment in self.segments
        ):
            raise ValueError("Every Path Segment must remain within the Energy Path horizon.")
        if any(segment.capability_id not in self.capability_ids for segment in self.segments):
            raise ValueError("Every Path Segment capability must be referenced by the Energy Path.")
        by_scope: dict[str, list[PathSegment]] = {}
        for segment in self.segments:
            by_scope.setdefault(segment.execution_scope_id, []).append(segment)
        for scope_segments in by_scope.values():
            ordered = sorted(scope_segments, key=lambda item: item.starts_at)
            overlaps = any(
                left.ends_at > right.starts_at
                for left, right in zip(ordered, ordered[1:], strict=False)
            )
            if overlaps:
                raise ValueError("Path Segments for one execution scope may not overlap.")

    def _validate_projected_states(self) -> None:
        times = [state.at for state in self.projected_states]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("Projected Energy States must be unique and time ordered.")
        if any(at < self.horizon_start or at > self.horizon_end for at in times):
            raise ValueError("Projected Energy States must remain within the Energy Path horizon.")

    @staticmethod
    def _require_unique_non_empty(values: tuple[str, ...], label: str) -> None:
        if any(not value.strip() for value in values):
            raise ValueError(f"Energy Path {label} IDs must not be empty.")
        if len(values) != len(set(values)):
            raise ValueError(f"Energy Path {label} IDs must be unique.")
