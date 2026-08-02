"""Runtime entry point with isolated read-only observation streams."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, cast

from picot.addon import runtime
from picot.addon.dashboard import publish_dashboard_states
from picot.addon.goodwe_dashboard import publish_goodwe_dashboard_states
from picot.addon.goodwe_observer import (
    read_goodwe_observation,
    unavailable_goodwe_observation,
)
from picot.addon.power_comparison import (
    add_power_comparison_fields,
    publish_power_comparison_states,
)
from picot.addon.zendure_dashboard import publish_zendure_dashboard_states
from picot.addon.zendure_observer import (
    read_zendure_observation,
    unavailable_zendure_observation,
)


def _goodwe_fields(token: str, *, observed_at: datetime) -> dict[str, object]:
    """Read GoodWe independently so a source failure cannot stop PicoT."""

    try:
        return read_goodwe_observation(
            runtime._request_json,
            token,
            observed_at=observed_at,
        )
    except Exception as exc:
        return unavailable_goodwe_observation(exc, observed_at=observed_at)


def _zendure_fields(token: str, *, observed_at: datetime) -> dict[str, object]:
    """Read Zendure independently so a source failure cannot stop PicoT."""

    try:
        return read_zendure_observation(
            runtime._request_json,
            token,
            observed_at=observed_at,
        )
    except Exception as exc:
        return unavailable_zendure_observation(exc, observed_at=observed_at)


def run_telemetry_once(
    options: dict[str, Any],
    token: str,
    planner_event: dict[str, object],
) -> dict[str, object]:
    """Refresh P1, Solcast, GoodWe and Zendure without changing the plan."""

    observed_at = datetime.now(runtime.LOCAL_TIMEZONE)
    event = dict(planner_event)
    event.update(runtime._grid_fields(options, token))
    event.update(runtime._solcast_fields(token, observed_at=observed_at))
    event.update(_goodwe_fields(token, observed_at=observed_at))
    event.update(_zendure_fields(token, observed_at=observed_at))
    event["telemetry_updated_at"] = observed_at.isoformat()
    event["telemetry_interval_seconds"] = int(options["telemetry_interval_seconds"])
    add_power_comparison_fields(event)

    publish_dashboard_states(event, token)
    publish_goodwe_dashboard_states(event, token)
    publish_zendure_dashboard_states(event, token)
    publish_power_comparison_states(event, token)
    return event


def _goodwe_log_event(event: dict[str, object]) -> dict[str, object]:
    """Return a compact dedicated log event for GoodWe observation."""

    return {
        "event": "picot_goodwe_snapshot",
        "status": event.get("goodwe_status"),
        "error": event.get("goodwe_error"),
        "solar_power_w": event.get("goodwe_solar_power_w"),
        "generation_today_kwh": event.get("goodwe_generation_today_kwh"),
        "generation_total_kwh": event.get("goodwe_generation_total_kwh"),
        "temperature_c": event.get("goodwe_temperature_c"),
        "observed_at": event.get("goodwe_observed_at"),
    }


def _zendure_log_event(event: dict[str, object]) -> dict[str, object]:
    """Return a compact dedicated log event for Zendure observation."""

    return {
        "event": "picot_zendure_snapshot",
        "status": event.get("zendure_status"),
        "error": event.get("zendure_error"),
        "soc_percent": event.get("zendure_soc_percent"),
        "actual_mode": event.get("zendure_actual_mode"),
        "requested_mode": event.get("zendure_requested_mode"),
        "signed_power_w": event.get("zendure_signed_power_w"),
        "charge_power_w": event.get("zendure_charge_power_w"),
        "discharge_power_w": event.get("zendure_discharge_power_w"),
        "power_consistent": event.get("zendure_power_consistent"),
        "observed_at": event.get("zendure_observed_at"),
    }


def main() -> int:
    """Run the existing planner with the expanded read-only observation loop."""

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN is unavailable; Home Assistant API access is required."
        )
    with runtime.OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))

    planner_interval = int(options["planner_interval_seconds"])
    telemetry_interval = int(options["telemetry_interval_seconds"])
    next_planner_run = 0.0
    next_telemetry_run = 0.0
    planner_event: dict[str, object] | None = None
    scheduled_boundary: runtime.ScheduledBoundary | None = None

    print("PicoT HEMS add-on starting", flush=True)
    while True:
        monotonic_now = time.monotonic()
        wall_clock_now = datetime.now(runtime.LOCAL_TIMEZONE)

        if scheduled_boundary is not None and wall_clock_now >= scheduled_boundary.occurs_at:
            try:
                assert planner_event is not None
                planner_event = runtime.run_scheduled_boundary_once(
                    options,
                    token,
                    planner_event,
                    scheduled_boundary,
                    now=wall_clock_now,
                )
                runtime._log_event(planner_event)
                scheduled_boundary = runtime._scheduled_boundary(
                    planner_event,
                    now=wall_clock_now,
                )
            except Exception as exc:
                runtime._log_runtime_error("scheduled_transition", exc)

        if monotonic_now >= next_planner_run:
            try:
                planner_event = runtime.run_planner_once(options, token)
                runtime._log_event(planner_event)
                scheduled_boundary = runtime._scheduled_boundary(
                    planner_event,
                    now=wall_clock_now,
                )
            except Exception as exc:
                runtime._log_runtime_error("planner", exc)
            next_planner_run = monotonic_now + planner_interval

        if planner_event is not None and monotonic_now >= next_telemetry_run:
            try:
                telemetry_event = run_telemetry_once(options, token, planner_event)
                runtime._log_event(runtime._solcast_log_event(telemetry_event))
                runtime._log_event(_goodwe_log_event(telemetry_event))
                runtime._log_event(_zendure_log_event(telemetry_event))
            except Exception as exc:
                runtime._log_runtime_error("telemetry", exc)
            next_telemetry_run = monotonic_now + telemetry_interval

        time.sleep(runtime.SCHEDULER_TICK_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
