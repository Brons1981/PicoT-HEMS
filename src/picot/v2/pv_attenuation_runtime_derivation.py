"""Derive observer-only PV attenuation ranges for the live horizon."""

from __future__ import annotations

from datetime import datetime

from picot.v2.contracts import (
    PVEnergyTimeline,
    PVForecastAttenuationProfile,
)
from picot.v2.pv_attenuation_range import (
    PVAttenuatedForecastRange,
    derive_pv_attenuated_forecast_range,
)

RUNTIME_DERIVATION_METHOD_VERSION = (
    "pv-attenuation-runtime-derivation:v1"
)


def derive_live_pv_attenuation_ranges(
    *,
    installation_scope_id: str,
    timeline: PVEnergyTimeline,
    profile: PVForecastAttenuationProfile | None,
    minutes_from_sunset_by_interval_id: dict[str, float],
    projected_at: datetime,
) -> tuple[PVAttenuatedForecastRange, ...]:
    """Derive every future forecast range without mutating the timeline."""

    if not installation_scope_id.strip():
        raise ValueError("installation_scope_id must be explicit")
    if projected_at.tzinfo is None or projected_at.utcoffset() is None:
        raise ValueError("projected_at must be timezone-aware")

    future_forecasts = tuple(
        interval
        for interval in timeline.intervals
        if interval.evidence_type == "FORECAST"
        and interval.starts_at >= projected_at
    )
    return tuple(
        derive_pv_attenuated_forecast_range(
            installation_scope_id=installation_scope_id,
            forecast=interval,
            profile=profile,
            minutes_from_sunset=(
                minutes_from_sunset_by_interval_id.get(
                    interval.interval_id
                )
            ),
            projected_at=projected_at,
        )
        for interval in future_forecasts
    )
