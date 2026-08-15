"""Deterministic sunset-relative offsets for future PV forecasts."""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite

from picot.v2.contracts import PVEnergyTimeline

SUNSET_OFFSET_METHOD_VERSION = "pv-sunset-offset:interval-midpoint:v1"


def derive_pv_sunset_offsets(
    *,
    timeline: PVEnergyTimeline,
    sunsets_by_local_date: dict[date, datetime],
    projected_at: datetime,
) -> dict[str, float]:
    """Return interval-midpoint offsets for future forecast intervals."""

    if projected_at.tzinfo is None or projected_at.utcoffset() is None:
        raise ValueError("projected_at must be timezone-aware")

    ordered_sunsets = tuple(
        sorted(sunsets_by_local_date.items(), key=lambda item: item[0])
    )
    for local_date, sunset_at in ordered_sunsets:
        if sunset_at.tzinfo is None or sunset_at.utcoffset() is None:
            raise ValueError("sunset values must be timezone-aware")
        if sunset_at.astimezone(sunset_at.tzinfo).date() != local_date:
            raise ValueError("sunset date must match its local date key")

    if not ordered_sunsets:
        return {}

    local_timezone = ordered_sunsets[0][1].tzinfo
    if local_timezone is None:
        raise ValueError("sunset values must be timezone-aware")
    if any(
        sunset_at.tzinfo != local_timezone
        for _, sunset_at in ordered_sunsets
    ):
        raise ValueError("sunset values must use one local timezone")

    offsets: dict[str, float] = {}
    for interval in timeline.intervals:
        if (
            interval.evidence_type != "FORECAST"
            or interval.starts_at < projected_at
        ):
            continue
        midpoint = interval.starts_at + (
            interval.ends_at - interval.starts_at
        ) / 2
        sunset_at = sunsets_by_local_date.get(
            midpoint.astimezone(local_timezone).date()
        )
        if sunset_at is None:
            continue
        minutes_from_sunset = (
            midpoint - sunset_at
        ).total_seconds() / 60.0
        if not isfinite(minutes_from_sunset):
            raise ValueError("sunset offset must be finite")
        offsets[interval.interval_id] = minutes_from_sunset

    return offsets
