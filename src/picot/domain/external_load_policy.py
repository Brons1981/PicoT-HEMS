"""Measured external demand and its explicitly delegated storage policy."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class ExternalLoadPolicy:
    source_id: str
    revision: str
    measured_at: datetime
    power_w: float
    storage_support_allowed: bool
    execution_scope_id: str
    session_id: str | None = None
    session_state: str | None = None
    planned_start: datetime | None = None
    expected_duration_seconds: float | None = None
    remaining_energy_wh: float | None = None
    expected_power_w: float | None = None
    physical_evidence_available: bool = False

    def __post_init__(self) -> None:
        if not self.source_id or not self.revision or not self.execution_scope_id:
            raise ValueError("external load policy requires provenance and scope")
        if self.measured_at.tzinfo is None or not isfinite(self.power_w) or self.power_w < 0:
            raise ValueError("external load policy requires dated finite demand")

        if self.session_id is not None:
            if (
                self.planned_start is None
                or self.planned_start.tzinfo is None
                or self.expected_duration_seconds is None
                or not isfinite(self.expected_duration_seconds)
                or self.expected_duration_seconds < 0
                or self.remaining_energy_wh is None
                or not isfinite(self.remaining_energy_wh)
                or self.remaining_energy_wh < 0
                or self.expected_power_w is None
                or not isfinite(self.expected_power_w)
                or self.expected_power_w <= 0
            ):
                raise ValueError("session demand requires dated finite forecast")
