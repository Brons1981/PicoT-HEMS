"""Deterministic ADR-037 household load forecast construction."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Protocol

from picot.v2.contracts import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)

INTERVAL_DURATION = timedelta(minutes=15)
HISTORICAL_METHOD_VERSION = "weighted-rolling-24h-periods:v1"
MINIMUM_HISTORICAL_PERIODS = 2
MAXIMUM_HISTORICAL_PERIODS = 7
MAXIMUM_LOOKBACK_DAYS = 14
FALLBACK_SOURCE_REFERENCE = "fallback:configured-power"
FALLBACK_METHOD_VERSION = (
    "constant-power-conservative-fallback:v1"
)


class _HouseholdLoadObservationLike(Protocol):
    @property
    def power_w(self) -> float: ...

    @property
    def sampled_at(self) -> datetime: ...


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _historical_window_mean(
    observations: Sequence[_HouseholdLoadObservationLike],
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> tuple[float, datetime, datetime] | None:
    window = tuple(
        observation
        for observation in observations
        if starts_at <= observation.sampled_at < ends_at
    )
    if len(window) < 2:
        return None

    first_sample = window[0].sampled_at
    last_sample = window[-1].sampled_at
    if last_sample - first_sample < (ends_at - starts_at) / 2:
        return None

    mean_power_w = (
        sum(observation.power_w for observation in window)
        / len(window)
    )
    return mean_power_w, first_sample, last_sample


def build_historical_household_load_forecast(
    *,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
    observations: Sequence[_HouseholdLoadObservationLike],
) -> HouseholdLoadForecast | None:
    """Build a deterministic forecast from comparable rolling periods."""
    if starts_at >= horizon_end:
        raise ValueError("starts_at must be before horizon_end")

    ordered_observations = tuple(
        sorted(
            observations,
            key=lambda observation: (
                observation.sampled_at,
                observation.power_w,
            ),
        )
    )
    intervals: list[HouseholdLoadForecastInterval] = []
    cursor = starts_at

    while cursor < horizon_end:
        ends_at = min(cursor + INTERVAL_DURATION, horizon_end)
        historical_periods: list[
            tuple[float, datetime, datetime]
        ] = []

        for days_ago in range(1, MAXIMUM_LOOKBACK_DAYS + 1):
            period = _historical_window_mean(
                ordered_observations,
                starts_at=cursor - timedelta(days=days_ago),
                ends_at=ends_at - timedelta(days=days_ago),
            )
            if period is not None:
                historical_periods.append(period)
            if len(historical_periods) == MAXIMUM_HISTORICAL_PERIODS:
                break

        if len(historical_periods) < MINIMUM_HISTORICAL_PERIODS:
            return None

        oldest_to_newest = tuple(reversed(historical_periods))
        total_weight = sum(
            range(1, len(oldest_to_newest) + 1)
        )
        weighted_power_w = sum(
            weight * period[0]
            for weight, period in enumerate(
                oldest_to_newest,
                start=1,
            )
        ) / total_weight
        expected_energy_wh = weighted_power_w * (
            (ends_at - cursor).total_seconds() / 3600.0
        )
        source_starts_at = min(
            period[1] for period in historical_periods
        )
        source_ends_at = max(
            period[2] for period in historical_periods
        )
        source_reference = (
            f"history:{source_starts_at.isoformat()}"
            f"..{source_ends_at.isoformat()}"
        )
        interval_seed = (
            f"{run_id}|{snapshot_id}|{cursor.isoformat()}|"
            f"{ends_at.isoformat()}|{expected_energy_wh}|"
            f"{source_reference}|{HISTORICAL_METHOD_VERSION}"
        )

        intervals.append(
            HouseholdLoadForecastInterval(
                interval_id=_stable_id(
                    "household-load-interval",
                    interval_seed,
                ),
                starts_at=cursor,
                ends_at=ends_at,
                expected_energy_wh=expected_energy_wh,
                confidence=(
                    len(historical_periods)
                    / MAXIMUM_HISTORICAL_PERIODS
                ),
                source_reference=source_reference,
                method_version=HISTORICAL_METHOD_VERSION,
            )
        )
        cursor = ends_at

    forecast_seed = (
        f"{run_id}|{snapshot_id}|{starts_at.isoformat()}|"
        f"{horizon_end.isoformat()}|{HISTORICAL_METHOD_VERSION}|"
        + "|".join(
            interval.interval_id for interval in intervals
        )
    )
    return HouseholdLoadForecast(
        forecast_id=_stable_id(
            "household-load-forecast",
            forecast_seed,
        ),
        run_id=run_id,
        snapshot_id=snapshot_id,
        intervals=tuple(intervals),
        fallback_active=False,
        fallback_reason=None,
    )


def derive_household_load_power_w(
    *,
    grid_power_w: float | None,
    pv_power_w: float | None,
    battery_power_w: float | None,
) -> float | None:
    """Derive valid household load from one complete power balance.

    Grid import and battery charging are positive. Grid export and battery
    discharging are negative.
    """
    if (
        grid_power_w is None
        or pv_power_w is None
        or battery_power_w is None
    ):
        return None
    values = (
        grid_power_w,
        pv_power_w,
        battery_power_w,
    )
    if any(isinstance(value, bool) for value in values):
        return None
    if not all(isfinite(value) for value in values):
        return None

    household_load_w = (
        pv_power_w
        + grid_power_w
        - battery_power_w
    )
    if not isfinite(household_load_w) or household_load_w < 0.0:
        return None
    return household_load_w


def build_fallback_household_load_forecast(
    *,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
    fallback_power_w: float,
    fallback_confidence: float,
) -> HouseholdLoadForecast:
    """Build an explicit low-confidence fallback over one rolling horizon."""
    if starts_at >= horizon_end:
        raise ValueError("starts_at must be before horizon_end")
    if fallback_power_w <= 0.0:
        raise ValueError("fallback_power_w must be positive")
    if not 0.0 < fallback_confidence <= 1.0:
        raise ValueError("fallback_confidence must be greater than 0 and at most 1")

    forecast_seed = (
        f"{run_id}|{snapshot_id}|{starts_at.isoformat()}|"
        f"{horizon_end.isoformat()}|{fallback_power_w}|"
        f"{fallback_confidence}|"
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
                confidence=fallback_confidence,
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
