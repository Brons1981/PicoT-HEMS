"""Deterministic ADR-037 household load forecast construction."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from picot.v2.contracts import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)

INTERVAL_DURATION = timedelta(minutes=15)
FALLBACK_SOURCE_REFERENCE = "fallback:configured-power"
FALLBACK_METHOD_VERSION = (
    "constant-power-conservative-fallback:v1"
)


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def build_fallback_household_load_forecast(
    *,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
    fallback_power_w: float,
) -> HouseholdLoadForecast:
    """Build an explicit low-confidence fallback over one rolling horizon."""
    if starts_at >= horizon_end:
        raise ValueError("starts_at must be before horizon_end")
    if fallback_power_w <= 0.0:
        raise ValueError("fallback_power_w must be positive")

    forecast_seed = (
        f"{run_id}|{snapshot_id}|{starts_at.isoformat()}|"
        f"{horizon_end.isoformat()}|{fallback_power_w}|"
        f"{FALLBACK_METHOD_VERSION}"
    )
    intervals: list[HouseholdLoadForecastInterval] = []
    cursor = starts_at

    while cursor < horizon_end:
        ends_at = min(cursor + INTERVAL_DURATION, horizon_end)
        duration_hours = (
            ends_at - cursor
        ).total_seconds() / 3600.0
        interval_seed = (
            f"{forecast_seed}|{cursor.isoformat()}|"
            f"{ends_at.isoformat()}"
        )
        intervals.append(
            HouseholdLoadForecastInterval(
                interval_id=_stable_id(
                    "household-load-interval",
                    interval_seed,
                ),
                starts_at=cursor,
                ends_at=ends_at,
                expected_energy_wh=(
                    fallback_power_w * duration_hours
                ),
                confidence=0.0,
                source_reference=FALLBACK_SOURCE_REFERENCE,
                method_version=FALLBACK_METHOD_VERSION,
            )
        )
        cursor = ends_at

    return HouseholdLoadForecast(
        forecast_id=_stable_id(
            "household-load-forecast",
            forecast_seed,
        ),
        run_id=run_id,
        snapshot_id=snapshot_id,
        intervals=tuple(intervals),
        fallback_active=True,
        fallback_reason="insufficient_history",
    )
