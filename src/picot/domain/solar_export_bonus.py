"""Explicit supplier bonus configuration and measured annual allowance evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class SolarExportBonusPolicy:
    enabled: bool
    effective_from: datetime
    latitude: float
    longitude: float
    annual_exported_kwh: float | None
    annual_exported_at: datetime | None
    timezone_name: str = "Europe/Amsterdam"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or self.effective_from.utcoffset() is None:
            raise ValueError("solar bonus requires explicit activation time")
        if (
            type(self.latitude) not in (int, float)
            or type(self.longitude) not in (int, float)
            or not isfinite(self.latitude)
            or not -90 <= self.latitude <= 90
            or not isfinite(self.longitude)
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("solar bonus requires valid installation coordinates")
        ZoneInfo(self.timezone_name)
        if self.annual_exported_kwh is not None and (
            type(self.annual_exported_kwh) not in (int, float)
            or not isfinite(self.annual_exported_kwh)
            or self.annual_exported_kwh < 0
        ):
            raise ValueError("annual exported energy must be finite and nonnegative")
        if self.annual_exported_at is not None and self.annual_exported_at.utcoffset() is None:
            raise ValueError("annual exported energy requires an aware observation time")
        if (self.annual_exported_kwh is None) != (self.annual_exported_at is None):
            raise ValueError("annual exported energy and its observation time belong together")


@dataclass(frozen=True, slots=True)
class SolarExportBonusContext:
    policy: SolarExportBonusPolicy
    observed_at: datetime
    annual_remaining_kwh: tuple[tuple[int, float], ...]
    evidence_ids: tuple[str, ...]
    status: str = "available"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.utcoffset() is None or not self.evidence_ids:
            raise ValueError("solar bonus context requires observation and provenance")
        years = [year for year, _ in self.annual_remaining_kwh]
        if len(years) != len(set(years)) or any(
            not isfinite(value) or not 0 <= value <= 7500 for _, value in self.annual_remaining_kwh
        ):
            raise ValueError("solar bonus allowance must be unique and bounded")
        if self.status not in {"available", "unavailable", "disabled"}:
            raise ValueError("invalid solar bonus evidence status")
