"""Canonical PV energy timeline assembly for ADR-039."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


@dataclass(frozen=True, slots=True)
class ActualPVEnergyInterval:
    """Validated measured PV energy over one elapsed interval."""

    starts_at: datetime
    ends_at: datetime
    energy_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_interval(self.starts_at, self.ends_at)
        if self.energy_wh < 0:
            raise ValueError("Actual PV energy must not be negative.")
        _validate_confidence(self.confidence)
        _validate_evidence(self.evidence_ids)


@dataclass(frozen=True, slots=True)
class ForecastPVPowerInterval:
    """Validated average PV power over one future interval."""

    starts_at: datetime
    ends_at: datetime
    average_power_w: float
    confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        _validate_interval(self.starts_at, self.ends_at)
        if self.average_power_w < 0:
            raise ValueError("Forecast PV average power must not be negative.")
        _validate_confidence(self.confidence)
        _validate_evidence(self.evidence_ids)
        if not self.method_version.strip():
            raise ValueError("Forecast PV method version must not be empty.")

    @property
    def energy_wh(self) -> float:
        """Convert validated interval-average power to interval energy."""

        duration_hours = (self.ends_at - self.starts_at).total_seconds() / 3600.0
        return self.average_power_w * duration_hours


def assemble_pv_energy_timeline(
    *,
    timeline_id: str,
    captured_at: datetime,
    horizon_end: datetime,
    actual_intervals: tuple[ActualPVEnergyInterval, ...],
    forecast_intervals: tuple[ForecastPVPowerInterval, ...],
) -> PVEnergyTimeline:
    """Assemble one contiguous timeline where reality ends exactly at capture time."""

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("PV timeline capture time must be timezone-aware.")
    if horizon_end.tzinfo is None or horizon_end.utcoffset() is None:
        raise ValueError("PV timeline horizon end must be timezone-aware.")
    if horizon_end <= captured_at:
        raise ValueError("PV timeline horizon end must be after capture time.")
    if not actual_intervals:
        raise ValueError("PV timeline assembly requires actual energy up to capture time.")
    if not forecast_intervals:
        raise ValueError("PV timeline assembly requires forecast energy after capture time.")

    _require_contiguous_actual(actual_intervals, captured_at)
    _require_contiguous_forecast(forecast_intervals, captured_at, horizon_end)

    intervals = tuple(
        PVEnergyTimelineInterval(
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            energy_wh=item.energy_wh,
            evidence_type=PVEnergyEvidenceType.ACTUAL,
            confidence=item.confidence,
            evidence_ids=item.evidence_ids,
        )
        for item in actual_intervals
    ) + tuple(
        PVEnergyTimelineInterval(
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            energy_wh=item.energy_wh,
            evidence_type=PVEnergyEvidenceType.FORECAST,
            confidence=item.confidence,
            evidence_ids=item.evidence_ids,
            method_version=item.method_version,
        )
        for item in forecast_intervals
    )

    return PVEnergyTimeline(
        timeline_id=timeline_id,
        created_at=captured_at,
        horizon_start=actual_intervals[0].starts_at,
        horizon_end=horizon_end,
        intervals=intervals,
    )


def _require_contiguous_actual(
    intervals: tuple[ActualPVEnergyInterval, ...], captured_at: datetime
) -> None:
    ordered = tuple(sorted(intervals, key=lambda item: item.starts_at))
    if ordered != intervals:
        raise ValueError("Actual PV intervals must be ordered.")
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current.starts_at != previous.ends_at:
            raise ValueError("Actual PV intervals must be contiguous.")
    if intervals[-1].ends_at != captured_at:
        raise ValueError("Actual PV energy must end exactly at snapshot capture time.")


def _require_contiguous_forecast(
    intervals: tuple[ForecastPVPowerInterval, ...],
    captured_at: datetime,
    horizon_end: datetime,
) -> None:
    ordered = tuple(sorted(intervals, key=lambda item: item.starts_at))
    if ordered != intervals:
        raise ValueError("Forecast PV intervals must be ordered.")
    if intervals[0].starts_at != captured_at:
        raise ValueError("Forecast PV energy must start exactly at snapshot capture time.")
    for previous, current in zip(intervals, intervals[1:], strict=False):
        if current.starts_at != previous.ends_at:
            raise ValueError("Forecast PV intervals must be contiguous.")
    if intervals[-1].ends_at != horizon_end:
        raise ValueError("Forecast PV energy must cover the complete planning horizon.")


def _validate_interval(starts_at: datetime, ends_at: datetime) -> None:
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValueError("PV interval start must be timezone-aware.")
    if ends_at.tzinfo is None or ends_at.utcoffset() is None:
        raise ValueError("PV interval end must be timezone-aware.")
    if ends_at <= starts_at:
        raise ValueError("PV interval must end after it starts.")


def _validate_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("PV confidence must be between 0.0 and 1.0.")


def _validate_evidence(evidence_ids: tuple[str, ...]) -> None:
    if not evidence_ids or any(not evidence_id.strip() for evidence_id in evidence_ids):
        raise ValueError("PV evidence IDs must not be empty.")
