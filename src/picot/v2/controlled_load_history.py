"""Measured load attribution at the HEMS boundary, independent of MEP."""

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Any

from picot.v2.contracts import HouseholdLoadForecast, HouseholdLoadForecastInterval
from picot.v2.household_load_forecast import (
    INTERVAL_DURATION,
    MAXIMUM_HISTORICAL_PERIODS,
    MAXIMUM_LOOKBACK_DAYS,
    MINIMUM_HISTORICAL_PERIODS,
)


def attribute(
    observation: Any,
    payload: Any,
    captured_at: datetime,
    balance_times: list[datetime | None] | None = None,
) -> Any:
    """Preserve physical total; unknown, skewed or impossible subsets stay unknown."""
    if observation is None or not isinstance(payload, dict):
        return observation
    try:
        power, source = payload["power_w"], payload["source_id"]
        generated = datetime.fromisoformat(payload["generated_at"])
        measured = datetime.fromisoformat(payload["measured_at"])
        if balance_times is not None and (
            len(balance_times) != 5
            or any(
                t is None
                or t.utcoffset() is None
                or not 0 <= (captured_at - t).total_seconds() <= 30
                or abs((measured - t).total_seconds()) > 30
                for t in balance_times
            )
        ):
            return observation
        if (
            payload["contract"] != "controlled-load-measurement:v1"
            or payload["status"] != "available"
            or type(power) not in (int, float)
            or not isfinite(power)
            or not 0 <= power <= observation.power_w - observation.identified_external_power_w
            or not isinstance(source, str)
            or len(source) != 64
            or any(c not in "0123456789abcdef" for c in source)
            or generated.utcoffset() is None
            or measured.utcoffset() is None
            or not 0 <= (captured_at - generated).total_seconds() <= 60
            or not 0 <= (generated - measured).total_seconds() <= 60
            or not 0 <= (observation.sampled_at - measured).total_seconds() <= 30
        ):
            return observation
        return replace(observation, controlled_power_w=float(power), controlled_source_id=source)
    except (KeyError, TypeError, ValueError, OverflowError):
        return observation


def paired_forecasts(
    observations: Any,
    *,
    source_id: str,
    run_id: str,
    snapshot_id: str,
    starts_at: datetime,
    horizon_end: datetime,
    require_complete: bool = False,
) -> Any:
    """Same samples and weights for total, residual and controlled contribution.

    This is a parallel historical model, NOT a correction to the active forecast.
    Old history with no matching measurement never becomes a zero observation.
    Input power has already had any separately identified EV load removed.
    With require_complete, use every sample selected by the active historical
    model and reject missing attribution instead of using a matched-only subset.
    """
    if not starts_at < horizon_end <= starts_at + timedelta(hours=49):
        return None
    # Index once rather than rescanning weeks of samples for every future quarter.
    buckets: dict[datetime, list[Any]] = {}
    for o in observations:
        if starts_at - timedelta(days=MAXIMUM_LOOKBACK_DAYS + 1) <= o.sampled_at <= starts_at and (
            require_complete
            or (
                o.controlled_source_id == source_id
                and o.controlled_power_w is not None
                and 0 <= o.controlled_power_w <= o.power_w
            )
        ):
            quarter = o.sampled_at.replace(
                minute=o.sampled_at.minute // 15 * 15, second=0, microsecond=0
            )
            buckets.setdefault(quarter, []).append(o)
    means = {}
    for quarter, samples in buckets.items():
        if (
            len(samples) >= 2
            and max(o.sampled_at for o in samples) - min(o.sampled_at for o in samples)
            >= INTERVAL_DURATION / 2
        ):
            means[quarter] = (
                sum(o.power_w for o in samples) / len(samples),
                sum(o.controlled_power_w for o in samples) / len(samples)
                if all(
                    o.controlled_source_id == source_id
                    and o.controlled_power_w is not None
                    and 0 <= o.controlled_power_w <= o.power_w
                    for o in samples
                )
                else None,
            )
    intervals: dict[str, list[HouseholdLoadForecastInterval]] = {
        kind: [] for kind in ("total", "residual", "controlled")
    }
    cursor = starts_at
    while cursor < horizon_end:
        quarter = cursor.replace(minute=cursor.minute // 15 * 15, second=0, microsecond=0)
        end = min(quarter + INTERVAL_DURATION, horizon_end)
        periods = [
            means[quarter - timedelta(days=d)]
            for d in range(1, MAXIMUM_LOOKBACK_DAYS + 1)
            if quarter - timedelta(days=d) in means
        ][:MAXIMUM_HISTORICAL_PERIODS]
        if len(periods) < MINIMUM_HISTORICAL_PERIODS or any(p[1] is None for p in periods):
            return None
        denominator = len(periods) * (len(periods) + 1) / 2
        total, controlled = (
            sum(w * p[column] for w, p in enumerate(reversed(periods), 1)) / denominator
            for column in (0, 1)
        )
        for kind, power in (
            ("total", total),
            ("residual", max(0, total - controlled)),
            ("controlled", controlled),
        ):
            energy = power * (end - cursor).total_seconds() / 3600
            seed = f"{snapshot_id}|{source_id}|{kind}|{cursor}|{end}|{energy}"
            intervals[kind].append(
                HouseholdLoadForecastInterval(
                    interval_id="paired-" + sha256(seed.encode()).hexdigest()[:16],
                    starts_at=cursor,
                    ends_at=end,
                    expected_energy_wh=energy,
                    confidence=len(periods) / MAXIMUM_HISTORICAL_PERIODS,
                    source_reference="paired-history:" + source_id,
                    method_version="paired-weighted-clock-quarter:v1",
                )
            )
        cursor = end
    return {
        kind: HouseholdLoadForecast(
            forecast_id="paired-"
            + sha256("|".join(i.interval_id for i in rows).encode()).hexdigest()[:16],
            run_id=run_id,
            snapshot_id=snapshot_id,
            intervals=tuple(rows),
            fallback_active=False,
            fallback_reason=None,
        )
        for kind, rows in intervals.items()
    }
