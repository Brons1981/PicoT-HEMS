"""Canonical immutable PV energy timeline from ADR-039."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PVEnergyEvidenceType(StrEnum):
    """Evidence basis used for one PV energy interval."""

    ACTUAL = "actual"
    FORECAST = "forecast"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class PVEnergyTimelineInterval:
    """PV energy contribution for one closed-open planning interval."""

    starts_at: datetime
    ends_at: datetime
    energy_wh: float
    evidence_type: PVEnergyEvidenceType
    confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str | None = None

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("PV interval start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("PV interval end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("PV interval must end after it starts.")
        if self.energy_wh < 0:
            raise ValueError("PV interval energy must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("PV interval confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids:
            raise ValueError("PV interval requires evidence IDs.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("PV interval evidence IDs must not be empty.")
        if self.method_version is not None and not self.method_version.strip():
            raise ValueError("PV interval method version must not be empty.")


@dataclass(frozen=True, slots=True)
class PVEnergyTimeline:
    """One immutable canonical PV energy interpretation for a Planner Run."""

    timeline_id: str
    created_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    intervals: tuple[PVEnergyTimelineInterval, ...]

    def __post_init__(self) -> None:
        if not self.timeline_id.strip():
            raise ValueError("PV energy timeline ID must not be empty.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("PV energy timeline creation time must be timezone-aware.")
        if self.horizon_start.tzinfo is None or self.horizon_start.utcoffset() is None:
            raise ValueError("PV energy timeline horizon start must be timezone-aware.")
        if self.horizon_end.tzinfo is None or self.horizon_end.utcoffset() is None:
            raise ValueError("PV energy timeline horizon end must be timezone-aware.")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("PV energy timeline horizon must end after it starts.")
        if not self.intervals:
            raise ValueError("PV energy timeline requires at least one interval.")

        ordered = tuple(sorted(self.intervals, key=lambda item: item.starts_at))
        if ordered != self.intervals:
            raise ValueError("PV energy timeline intervals must be ordered.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("PV energy timeline must start at its declared horizon start.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("PV energy timeline must end at its declared horizon end.")
        for previous, current in zip(self.intervals, self.intervals[1:], strict=False):
            if current.starts_at != previous.ends_at:
                raise ValueError("PV energy timeline intervals must be contiguous.")

    @property
    def total_energy_wh(self) -> float:
        """Return total PV energy represented by the canonical timeline."""

        return sum(interval.energy_wh for interval in self.intervals)
