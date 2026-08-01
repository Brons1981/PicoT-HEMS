"""Immutable input envelope for one deterministic Planner Run.

The snapshot contains only PicoT domain data. It never contains Home Assistant
entity IDs, vendor objects or live integration handles. See ADR-017 and ADR-028.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.objectives import PlannerStrategy


class RuntimePressureState(StrEnum):
    """Runtime resource state captured for a Planner Run."""

    NORMAL = "normal"
    TRANSIENT_PRESSURE = "transient_pressure"
    SUSTAINED_PRESSURE = "sustained_pressure"


@dataclass(frozen=True, slots=True)
class PlanningInputVersions:
    """Versions of mutable input groups captured in one atomic snapshot."""

    capability_mapping: int
    user_rules: int
    commitments: int
    household_state: int
    forecasts: int

    def __post_init__(self) -> None:
        for name, value in (
            ("capability_mapping", self.capability_mapping),
            ("user_rules", self.user_rules),
            ("commitments", self.commitments),
            ("household_state", self.household_state),
            ("forecasts", self.forecasts),
        ):
            if value < 1:
                raise ValueError(f"{name} version must be at least 1.")


@dataclass(frozen=True, slots=True)
class PlanningInputSnapshot:
    """Atomic and immutable temporal input envelope for one Planner Run.

    Typed household, forecast, capability, rule and commitment sections will be
    added as their domain contracts are implemented. Their exact captured
    revisions are already represented by ``versions``.
    """

    snapshot_id: str
    captured_at: datetime
    horizon_end: datetime
    strategy: PlannerStrategy
    runtime_state: RuntimePressureState
    versions: PlanningInputVersions
    replan_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("Snapshot ID must not be empty.")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("Snapshot capture time must be timezone-aware.")
        if self.horizon_end.tzinfo is None or self.horizon_end.utcoffset() is None:
            raise ValueError("Planning horizon end must be timezone-aware.")
        if self.horizon_end <= self.captured_at:
            raise ValueError("Planning horizon must end after snapshot capture time.")
        if not self.replan_reasons:
            raise ValueError("A Planning Input Snapshot requires a replan reason.")
        if any(not reason.strip() for reason in self.replan_reasons):
            raise ValueError("Replan reasons must not be empty.")
