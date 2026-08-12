"""Deterministic household-load forecast model from ADR-037."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class HouseholdLoadForecastInterval:
    """Expected non-controlled household energy for one forecast interval."""

    starts_at: datetime
    ends_at: datetime
    expected_energy_wh: float
    confidence: float

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("Household load interval start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("Household load interval end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Household load interval must end after it starts.")
        if self.expected_energy_wh < 0:
            raise ValueError("Expected household energy must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Household load confidence must be between 0.0 and 1.0.")


@dataclass(frozen=True, slots=True)
class HouseholdLoadForecast:
    """Versioned, explainable baseline household-demand forecast."""

    forecast_id: str
    created_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    intervals: tuple[HouseholdLoadForecastInterval, ...]
    historical_source_reference: str
    method_version: str

    def __post_init__(self) -> None:
        if not self.forecast_id.strip():
            raise ValueError("Household load forecast ID must not be empty.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Household load forecast creation time must be timezone-aware.")
        if self.horizon_start.tzinfo is None or self.horizon_start.utcoffset() is None:
            raise ValueError("Household load forecast horizon start must be timezone-aware.")
        if self.horizon_end.tzinfo is None or self.horizon_end.utcoffset() is None:
            raise ValueError("Household load forecast horizon end must be timezone-aware.")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("Household load forecast horizon must end after it starts.")
        if not self.historical_source_reference.strip():
            raise ValueError("Historical source reference must not be empty.")
        if not self.method_version.strip():
            raise ValueError("Forecast method version must not be empty.")
        if not self.intervals:
            raise ValueError("Household load forecast requires at least one interval.")

        ordered = tuple(sorted(self.intervals, key=lambda item: item.starts_at))
        if ordered != self.intervals:
            raise ValueError("Household load forecast intervals must be ordered.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("Household load forecast must start at its declared horizon start.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("Household load forecast must end at its declared horizon end.")
        for previous, current in zip(self.intervals, self.intervals[1:], strict=False):
            if current.starts_at != previous.ends_at:
                raise ValueError("Household load forecast intervals must be contiguous.")

    @property
    def confidence(self) -> float:
        """Conservative aggregate confidence across the complete forecast horizon."""

        return min(interval.confidence for interval in self.intervals)

    @property
    def expected_energy_wh(self) -> float:
        """Total expected baseline household demand over the horizon."""

        return sum(interval.expected_energy_wh for interval in self.intervals)
