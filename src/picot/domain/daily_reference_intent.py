"""Explicit physical intent schedules for the independent daily simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DailyStorageIntent(StrEnum):
    """Delegated storage behaviours that can be simulated without live control."""

    HOUSEHOLD_SUPPORT_ONLY = "household_support_only"
    NOM = "nom"
    STANDBY = "standby"
    GRID_REQUIREMENT = "grid_requirement"
    STORAGE_EXPORT = "storage_export"


@dataclass(frozen=True, slots=True)
class DailyReferenceIntentInterval:
    """One physical delegated intent over an exact simulation interval."""

    starts_at: datetime
    ends_at: datetime
    intent: DailyStorageIntent
    storage_export_target_wh: float = 0.0

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("Daily intent start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("Daily intent end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Daily intent interval must end after it starts.")
        if self.storage_export_target_wh < 0.0:
            raise ValueError("Daily storage export target must not be negative.")
        if (
            self.intent is DailyStorageIntent.STORAGE_EXPORT
            and self.storage_export_target_wh <= 0.0
        ):
            raise ValueError("Storage export intent requires a positive export target.")
        if (
            self.intent is not DailyStorageIntent.STORAGE_EXPORT
            and self.storage_export_target_wh > 0.0
        ):
            raise ValueError("Only storage export intent may request storage export.")


@dataclass(frozen=True, slots=True)
class DailyReferenceIntentSchedule:
    """Complete physical intent schedule for one independent simulation horizon."""

    schedule_id: str
    snapshot_id: str
    horizon_start: datetime
    horizon_end: datetime
    intervals: tuple[DailyReferenceIntentInterval, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.schedule_id.strip() or not self.snapshot_id.strip():
            raise ValueError("Daily intent schedule identity must be explicit.")
        if self.horizon_end <= self.horizon_start or not self.intervals:
            raise ValueError("Daily intent schedule requires a complete horizon.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("Daily intent schedule must start at its horizon.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("Daily intent schedule must end at its horizon.")
        if any(
            left.ends_at != right.starts_at
            for left, right in zip(self.intervals, self.intervals[1:], strict=False)
        ):
            raise ValueError("Daily intent schedule intervals must be contiguous.")
        if not self.method_version.strip():
            raise ValueError("Daily intent schedule method version must be explicit.")
