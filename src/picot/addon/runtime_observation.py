"""Runtime entry point with isolated direct-source observation streams."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, cast

from picot.addon import price_runtime_v2, runtime
from picot.addon.dashboard import publish_dashboard_states
from picot.addon.goodwe_dashboard import publish_goodwe_dashboard_states
from picot.addon.goodwe_observer import (
    DEFAULT_GOODWE_POWER_ENTITY,
    read_goodwe_observation,
    unavailable_goodwe_observation,
)
from picot.addon.power_comparison import (
    add_power_comparison_fields,
    publish_power_comparison_states,
)
from picot.addon.pv_forecast_comparison import (
    add_pv_forecast_comparison_fields,
    pv_forecast_comparison_log_event,
)
from picot.addon.zendure_dashboard import publish_zendure_dashboard_states
from picot.addon.zendure_observer import (
    DEFAULT_ZENDURE_POWER_ENTITY,
    read_zendure_observation,
    unavailable_zendure_observation,
)


def _goodwe_fields(
    options: dict[str, Any],
    token: str,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Read the configured physical GoodWe source directly."""

    power_entity = str(options.get("pv_power_entity", DEFAULT_GOODWE_POWER_ENTITY))
    try:
        return read_goodwe_observation(
            runtime._request_json,
            token,
            observed_at=observed_at,
            power_entity=power_entity,
        )
    except Exception as exc:
        return unavailable_goodwe_observation(
            exc,
            observed_at=observed_at,
            power_entity=power_entity,
        )


def _zendure_fields(
    options: dict[str, Any],
    token: str,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Read the configured physical Zendure source directly."""

    power_entity = str(
        options.get("battery_power_entity", DEFAULT_ZENDURE_POWER_ENTITY)
    )
    try:
        fields = read_zendure_observation(
            runtime._request_json,
            token,
            observed_at=observed_at,
            power_entity=power_entity,
        )
    except Exception as exc:
        return unavailable_zendure_observation(
            exc,
            observed_at=observed_at,
            power_entity=power_entity,
        )

    signed_power = fields.get("zendure_signed_power_w")
    if (
        isinstance(signed_power, (int, float))
        and not isinstance(signed_power, bool)
        and not bool(options.get("battery_charge_is_positive", True))
    ):
        normalized = -float(signed_power)
        fields["zendure_signed_power_w"] = normalized
        fields["zendure_charge_power_w"] = max(0.0, normalized)
        fields["zendure_discharge_power_w"] = max(0.0, -normalized)
    return fields


def _run_price_planner_once(
    options: dict[str, Any],
    token: str,
) -> dict[str, object]:
    """Run the explicitly configured price strategy, defaulting safely to v1."""

    strategy = str(options.get("price_strategy", "v1"))
    if strategy == "v1":
        return runtime.run_planner_once(options, token)
    if strategy == "v2":
        return price_runtime_v2.run_planner_once(options, token)
    raise ValueError(f"Unsupported price_strategy: {strategy}")


def run_telemetry_once(
    options: dict[str, Any],
    token: str,
    planner_event: dict[str, object],
) -> dict[str, object]:
    """Refresh direct P1, Solcast, GoodWe and Zendure observations."""

    observed_at = datetime.now(runtime.LOCAL_TIMEZONE)
    event = dict(planner_event)
    event.update(runtime._grid_fields(options, token))
    event.update(runtime._solcast_fields(token, observed_at=observed_at))
    event.update(_goodwe_fields(options, token, observed_at=observed_at))
    event.update(_zendure_fields(options, token, observed_at=observed_at))
    event["telemetry_updated_at"] = observed_at.isoformat()
    event["telemetry_interval_seconds"] = int(options["telemetry_interval_seconds"])
    add_power_comparison_fields(event)
    add_pv_forecast_comparison_fields(event)

    # Mirror entities remain temporarily for migration and diagnostics only.
    # Planner and runtime input use the physical entities above directly.
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
        "source_entity": event.get("goodwe_power_entity"),
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
        "source_entity": event.get("zendure_power_entity"),
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
    """Run the selected planner with direct physical observation inputs."""

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
                planner_event = _run_price_planner_once(options, token)
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
                runtime._log_event(
                    pv_forecast_comparison_log_event(telemetry_event)
                )
            except Exception as exc:
                runtime._log_runtime_error("telemetry", exc)
            next_telemetry_run = monotonic_now + telemetry_interval

        time.sleep(runtime.SCHEDULER_TICK_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
