"""Immutable forecast domain models used by the Planning Pipeline.

Forecasts are source-independent PicoT domain data. They carry explicit
freshness, temporal coverage and confidence metadata as required by ADR-017.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ForecastKind(StrEnum):
    """Forecast categories currently understood by the PicoT Core."""

    ENERGY_PRICE = "energy_price"
    PV_POWER = "pv_power"
    HOUSEHOLD_LOAD = "household_load"


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One immutable forecast value over a closed-open time interval."""

    starts_at: datetime
    ends_at: datetime
    value: float
    confidence: float

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("Forecast point start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("Forecast point end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Forecast point must end after it starts.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Forecast confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class ForecastSeries:
    """Versioned forecast series from one logical source."""

    forecast_id: str
    kind: ForecastKind
    source: str
    created_at: datetime
    expires_at: datetime
    unit: str
    points: tuple[ForecastPoint, ...]

    def __post_init__(self) -> None:
        if not self.forecast_id.strip():
            raise ValueError("Forecast ID must not be empty.")
        if not self.source.strip():
            raise ValueError("Forecast source must not be empty.")
        if not self.unit.strip():
            raise ValueError("Forecast unit must not be empty.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Forecast creation time must be timezone-aware.")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Forecast expiry time must be timezone-aware.")
        if self.expires_at <= self.created_at:
            raise ValueError("Forecast expiry must be after creation time.")
        if not self.points:
            raise ValueError("Forecast series requires at least one point.")
        ordered = tuple(sorted(self.points, key=lambda point: point.starts_at))
        if ordered != self.points:
            raise ValueError("Forecast points must be ordered by start time.")
        for previous, current in zip(self.points, self.points[1:], strict=False):
            if current.starts_at < previous.ends_at:
                raise ValueError("Forecast points must not overlap.")
        if self.points[-1].ends_at > self.expires_at:
            raise ValueError("Forecast points may not extend beyond forecast expiry.")

    def is_expired_at(self, moment: datetime) -> bool:
        """Return whether the forecast is expired at the supplied aware time."""

        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Expiry check time must be timezone-aware.")
        return moment >= self.expires_at


@dataclass(frozen=True, slots=True)
class ForecastSet:
    """Immutable collection of forecasts captured for one Planner Run."""

    series: tuple[ForecastSeries, ...]

    def __post_init__(self) -> None:
        ids = [item.forecast_id for item in self.series]
        if len(ids) != len(set(ids)):
            raise ValueError("Each forecast ID may appear only once.")

    def by_kind(self, kind: ForecastKind) -> tuple[ForecastSeries, ...]:
        """Return all forecast series of one kind in stored order."""

        return tuple(item for item in self.series if item.kind is kind)
