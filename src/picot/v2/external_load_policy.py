"""One optional Energy Devices snapshot boundary; no vendor mode selection."""

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import cast

from picot.domain.external_load_policy import ExternalLoadPolicy
from picot.v2.contracts import HouseholdLoadForecast

METHOD = "measured-external-load-support-policy:v1"
SESSION_METHOD = "energy-device-session-demand:v1"


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
        return ExternalLoadPolicy(
            source,
            revision,
            when,
            float(power),
            False,
            execution_scope_id,
            physical_evidence_available=True,
        )
    except (KeyError, ValueError):
        return None


def read_session_demand(
    payload: dict[str, object] | None,
    *,
    captured_at: datetime,
    execution_scope_id: str,
    live_policy: ExternalLoadPolicy | None = None,
) -> ExternalLoadPolicy | None:
    """Admit explicitly confirmed demand independently of regulation authority."""
    if (
        not payload
        or payload.get("contract") != SESSION_METHOD
        or payload.get("source_id") != "energy-devices:ev-session"
    ):
        return None
    try:
        stamp = payload.get("generated_at")
        if not isinstance(stamp, str):
            return None
        generated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if generated.tzinfo is None or not 0 <= (captured_at - generated).total_seconds() <= 15:
            return None
        session = payload.get("session")
        if not isinstance(session, dict) or session.get("confirmed") is not True:
            return None
        state = session.get("state")
        if state not in {"planned", "active", "interrupted"}:
            return None
        start_raw = session.get("planned_start")
        if not isinstance(start_raw, str):
            return None
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        remaining = session.get("remaining_energy_wh")
        expected = session.get("expected_power_w")
        duration = session.get("expected_duration_seconds")
        for value in (remaining, expected, duration):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                return None
        remaining = cast(float, remaining)
        expected = cast(float, expected)
        duration = cast(float, duration)
        if not 0 <= remaining <= 88320 or not 100 <= expected <= 3680 or not 0 < duration <= 86400:
            return None
        if start.tzinfo is None:
            return None
        start + timedelta(seconds=duration)  # reject an unrepresentable deadline
        actual = session.get("current_power_w")
        physical = 0.0
        physical_available = False
        measured = session.get("last_measured_at")
        if (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isfinite(actual)
            and actual >= 0
            and isinstance(measured, str)
        ):
            when = datetime.fromisoformat(measured.replace("Z", "+00:00"))
            if when.tzinfo is not None and 0 <= (captured_at - when).total_seconds() <= 15:
                physical = float(actual)
                physical_available = True
        if not physical_available:
            if session.get("switch_state") == "off":
                physical_available = True  # a confirmed off charger cannot supply the EV
            else:
                return None  # do not add a profile to an unseparated live household load
        session_id = session.get("session_id")
        version = session.get("version")
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
        ):
            return None
        return ExternalLoadPolicy(
            "energy-devices:ev-session",
            str(version),
            generated,
            physical,
            live_policy.storage_support_allowed if live_policy is not None else True,
            execution_scope_id,
            session_id,
            str(state),
            start,
            float(duration),
            float(remaining),
            float(expected),
            physical_evidence_available=physical_available,
        )
    except (ValueError, TypeError, OverflowError):
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
    if policy.session_id is not None:
        if not policy.remaining_energy_wh or not policy.expected_power_w:
            return forecast
        start = max(captured_at, policy.planned_start or captured_at)
        power = policy.expected_power_w
        end = start + timedelta(seconds=policy.remaining_energy_wh * 3600 / power)
        deadline = (policy.planned_start or captured_at) + timedelta(
            seconds=policy.expected_duration_seconds or 0
        )
        end = min(end, deadline)
        if end <= start:
            return forecast
    else:
        if policy.storage_support_allowed or policy.power_w <= 0:
            return forecast
        start, power = captured_at, policy.power_w
        end = captured_at + timedelta(minutes=15)
    intervals = []
    for interval in forecast.intervals:
        cuts = sorted(
            {interval.starts_at, interval.ends_at}
            | {b for b in (start, end) if interval.starts_at < b < interval.ends_at}
        )
        for left, right in zip(cuts, cuts[1:], strict=False):
            seconds = (right - left).total_seconds()
            fraction = seconds / (interval.ends_at - interval.starts_at).total_seconds()
            energy = interval.expected_energy_wh * fraction
            excluded = interval.battery_excluded_energy_wh * fraction
            in_session = start <= left < end
            if in_session:
                energy += power * seconds / 3600
                excluded += power * seconds / 3600 if not policy.storage_support_allowed else 0.0
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
                    confidence=min(interval.confidence, 0.5)
                    if policy.session_id and in_session
                    else interval.confidence,
                    method_version=SESSION_METHOD if policy.session_id else METHOD,
                )
            )
    forecast_digest = sha256("|".join(i.interval_id for i in intervals).encode()).hexdigest()[:16]
    return replace(
        forecast, forecast_id=f"external-load-{forecast_digest}", intervals=tuple(intervals)
    )
