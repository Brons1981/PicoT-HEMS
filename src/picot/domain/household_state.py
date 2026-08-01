"""Household electrical state used by the PicoT Planner.

The model represents the physical installation as observed. It contains no
Home Assistant entities or vendor-specific identifiers. See ADR-029.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Phase(StrEnum):
    """Electrical phase identifier."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True, slots=True)
class PhaseState:
    """Immutable measured and configured state for one electrical phase."""

    phase: Phase
    current_a: float | None
    voltage_v: float | None
    active_power_w: float | None
    main_fuse_limit_a: float
    operational_margin_a: float = 0.0

    def __post_init__(self) -> None:
        if self.current_a is not None and self.current_a < 0:
            raise ValueError("Phase current must not be negative.")
        if self.voltage_v is not None and self.voltage_v <= 0:
            raise ValueError("Phase voltage must be greater than zero.")
        if self.main_fuse_limit_a <= 0:
            raise ValueError("Main fuse limit must be greater than zero.")
        if not 0 <= self.operational_margin_a < self.main_fuse_limit_a:
            raise ValueError("Operational margin must be non-negative and below the fuse limit.")

    @property
    def operational_limit_a(self) -> float:
        """Maximum planned current after applying the configured margin."""

        return self.main_fuse_limit_a - self.operational_margin_a

    @property
    def available_current_a(self) -> float | None:
        """Remaining planned current, or None when current is unavailable."""

        if self.current_a is None:
            return None
        return max(0.0, self.operational_limit_a - self.current_a)


@dataclass(frozen=True, slots=True)
class HouseholdState:
    """Atomic household energy state captured for one Planning Input Snapshot."""

    measured_at: datetime
    phases: tuple[PhaseState, ...]
    grid_power_w: float | None = None
    pv_power_w: float | None = None
    battery_power_w: float | None = None
    household_load_w: float | None = None

    def __post_init__(self) -> None:
        if self.measured_at.tzinfo is None or self.measured_at.utcoffset() is None:
            raise ValueError("Household state time must be timezone-aware.")
        phase_ids = [item.phase for item in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("Each electrical phase may appear only once.")
        if len(self.phases) > 3:
            raise ValueError("A household state may contain at most three phases.")
