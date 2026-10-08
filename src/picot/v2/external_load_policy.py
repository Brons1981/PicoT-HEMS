"""One optional Energy Devices snapshot boundary; no vendor mode selection."""

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite

from picot.domain.external_load_policy import ExternalLoadPolicy
from picot.v2.contracts import HouseholdLoadForecast

METHOD = "measured-external-load-support-policy:v1"


def read_external_load_policy(
    payload: dict[str, object] | None,
    *,
    captured_at: datetime,
    execution_scope_id: str,
) -> ExternalLoadPolicy | None:
    if not payload or payload.get("contract") != METHOD:
        return None
    # A shadow estimate never proves that storage exclusion is actually enabled.
    if payload.get("control_enabled") is not True or payload.get("status") != "ready":
        return None
    try:
        raw = payload["measured_at"]
        if not isinstance(raw, str):
            return None
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        power = payload["ev_w"]
        if isinstance(power, bool) or not isinstance(power, (float, int)):
            return None
        if when.tzinfo is None or not 0 <= (captured_at - when).total_seconds() <= 3:
            return None
        if not isfinite(power) or power < 0:
            return None
        source = payload.get("source_id")
        revision = payload.get("revision")
        if not isinstance(source, str) or not isinstance(revision, str):
            return None
        return ExternalLoadPolicy(source, revision, when, float(power), False, execution_scope_id)
    except (KeyError, ValueError):
        return None


def apply_external_load_policy(
    forecast: HouseholdLoadForecast,
    policy: ExternalLoadPolicy,
    *,
    captured_at: datetime,
) -> HouseholdLoadForecast:
    """Add observed EV for 15m to a baseline with identified EV disaggregated.

    The ingestion boundary removes identified EV from the baseline/guard view,
    but preserves physical observations. This contribution replaces on every
    snapshot; it is not accumulated. Costs and grid energy remain physical.
    """
    if policy.storage_support_allowed or policy.power_w <= 0:
        return forecast
    end = captured_at + timedelta(minutes=15)
    intervals = []
    for interval in forecast.intervals:
        cuts = sorted(
            {interval.starts_at, interval.ends_at}
            | {b for b in (captured_at, end) if interval.starts_at < b < interval.ends_at}
        )
        for left, right in zip(cuts, cuts[1:], strict=False):
            seconds = (right - left).total_seconds()
            fraction = seconds / (interval.ends_at - interval.starts_at).total_seconds()
            energy = interval.expected_energy_wh * fraction
            excluded = interval.battery_excluded_energy_wh * fraction
            if captured_at <= left < end:
                energy += policy.power_w * seconds / 3600
                excluded = policy.power_w * seconds / 3600
            digest = sha256(f"{interval.interval_id}|{left}|{right}|{energy}|{excluded}".encode())
            intervals.append(
                replace(
                    interval,
                    interval_id=f"external-load-{digest.hexdigest()[:16]}",
                    starts_at=left,
                    ends_at=right,
                    expected_energy_wh=energy,
                    battery_excluded_energy_wh=excluded,
                    source_reference=f"{interval.source_reference};{policy.source_id}:{policy.revision}",
                    method_version=METHOD,
                )
            )
    forecast_digest = sha256("|".join(i.interval_id for i in intervals).encode()).hexdigest()[:16]
    return replace(
        forecast, forecast_id=f"external-load-{forecast_digest}", intervals=tuple(intervals)
    )
