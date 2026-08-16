"""Deterministic historical solar context alignment for PV evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from picot.v2.pv_deviation import PVDeviationResult
from picot.v2.pv_solar_history import SolarContextObservation

SOLAR_CONTEXT_ALIGNMENT_METHOD_VERSION = "pv-solar-context-alignment:v1"


@dataclass(frozen=True, slots=True)
class SolarContextAlignmentResult:
    """Traceable solar context selected for one closed PV interval."""

    deviation_id: str
    interval_midpoint: datetime
    status: str
    reason: str | None
    solar_observation_evidence_id: str | None
    solar_observation_sampled_at: datetime | None
    solar_azimuth_degrees: float | None
    solar_elevation_degrees: float | None
    sunset_at: datetime | None
    observation_age_seconds: float | None
    method_version: str


def align_solar_context_to_deviation(
    *,
    deviation: PVDeviationResult,
    observations: tuple[SolarContextObservation, ...],
    local_timezone: tzinfo,
    maximum_age_seconds: float,
) -> SolarContextAlignmentResult:
    """Select the latest non-future observation without interpolation."""
    if maximum_age_seconds <= 0:
        raise ValueError("maximum_age_seconds must be positive")
    if (
        deviation.starts_at.tzinfo is None
        or deviation.starts_at.utcoffset() is None
        or deviation.ends_at.tzinfo is None
        or deviation.ends_at.utcoffset() is None
        or deviation.evaluated_at.tzinfo is None
        or deviation.evaluated_at.utcoffset() is None
    ):
        raise ValueError("deviation timestamps must be timezone-aware")
    if deviation.ends_at <= deviation.starts_at:
        raise ValueError("deviation interval must have positive duration")
    if deviation.evaluated_at < deviation.ends_at:
        raise ValueError("deviation interval must be closed")

    midpoint = deviation.starts_at + (
        deviation.ends_at - deviation.starts_at
    ) / 2
    candidates = tuple(
        observation
        for observation in observations
        if observation.sampled_at <= midpoint
    )
    if not candidates:
        return _result(
            deviation_id=deviation.deviation_id,
            interval_midpoint=midpoint,
            status="unavailable",
            reason="no_observation_at_or_before_midpoint",
        )

    selected = max(
        candidates,
        key=lambda observation: (
            observation.sampled_at,
            observation.evidence_id,
        ),
    )
    age_seconds = (
        midpoint - selected.sampled_at
    ).total_seconds()
    if age_seconds > maximum_age_seconds:
        return _result(
            deviation_id=deviation.deviation_id,
            interval_midpoint=midpoint,
            status="unavailable",
            reason="observation_stale",
            observation=selected,
            observation_age_seconds=age_seconds,
        )

    midpoint_local_date = midpoint.astimezone(local_timezone).date()
    sunset_local_date = selected.sunset_at.astimezone(
        local_timezone
    ).date()
    if sunset_local_date != midpoint_local_date:
        return _result(
            deviation_id=deviation.deviation_id,
            interval_midpoint=midpoint,
            status="unavailable",
            reason="sunset_local_date_mismatch",
            observation=selected,
            observation_age_seconds=age_seconds,
        )

    return _result(
        deviation_id=deviation.deviation_id,
        interval_midpoint=midpoint,
        status="aligned",
        reason=None,
        observation=selected,
        observation_age_seconds=age_seconds,
    )


def _result(
    *,
    deviation_id: str,
    interval_midpoint: datetime,
    status: str,
    reason: str | None,
    observation: SolarContextObservation | None = None,
    observation_age_seconds: float | None = None,
) -> SolarContextAlignmentResult:
    return SolarContextAlignmentResult(
        deviation_id=deviation_id,
        interval_midpoint=interval_midpoint,
        status=status,
        reason=reason,
        solar_observation_evidence_id=(
            observation.evidence_id if observation is not None else None
        ),
        solar_observation_sampled_at=(
            observation.sampled_at if observation is not None else None
        ),
        solar_azimuth_degrees=(
            observation.solar_azimuth_degrees
            if observation is not None
            else None
        ),
        solar_elevation_degrees=(
            observation.solar_elevation_degrees
            if observation is not None
            else None
        ),
        sunset_at=(
            observation.sunset_at if observation is not None else None
        ),
        observation_age_seconds=observation_age_seconds,
        method_version=SOLAR_CONTEXT_ALIGNMENT_METHOD_VERSION,
    )
