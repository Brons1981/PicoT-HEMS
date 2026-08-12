"""Canonical closed-loop household flow evidence for one Planner Run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CurrentFlowObservation:
    """Debounced current-flow evidence captured atomically with planning inputs."""

    observation_id: str
    observed_at: datetime
    grid_export_w: float
    battery_discharge_w: float
    pv_power_w: float
    discharge_while_exporting: bool
    persistent_mismatch: bool
    consecutive_samples: int
    required_samples: int
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("Flow observation ID must not be empty.")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Flow observation time must be timezone-aware.")
        for value, label in (
            (self.grid_export_w, "Grid export power"),
            (self.battery_discharge_w, "Battery discharge power"),
            (self.pv_power_w, "PV power"),
        ):
            if value < 0:
                raise ValueError(f"{label} must not be negative.")
        if self.consecutive_samples < 0:
            raise ValueError("Flow observation sample count must not be negative.")
        if self.required_samples < 1:
            raise ValueError("Flow observation required sample count must be at least 1.")
        if self.persistent_mismatch and not self.discharge_while_exporting:
            raise ValueError("Persistent flow mismatch requires a current contradiction.")
        if self.persistent_mismatch and self.consecutive_samples < self.required_samples:
            raise ValueError("Persistent flow mismatch requires enough consecutive samples.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Flow observation evidence IDs must not be empty.")
