"""Canonical closed-loop household flow evidence for one Planner Run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CurrentFlowObservation:
    """Time-based current-flow evidence captured atomically with planning inputs."""

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
    control_regime: str | None = None
    validation_band: str | None = None
    tracking_deviation_w: float | None = None
    grey_elapsed_s: float = 0.0
    red_elapsed_s: float = 0.0

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
        if self.required_samples < 0:
            raise ValueError("Flow observation required sample count must not be negative.")
        if self.tracking_deviation_w is not None and self.tracking_deviation_w < 0:
            raise ValueError("Tracking deviation must not be negative.")
        if self.grey_elapsed_s < 0 or self.red_elapsed_s < 0:
            raise ValueError("Flow observation elapsed times must not be negative.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Flow observation evidence IDs must not be empty.")
