"""Runtime entry point with isolated direct-source observation streams."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, cast

from picot.addon import price_runtime_v2, runtime
from picot.addon.dashboard import publish_dashboard_states
from picot.addon.diagnostics_dashboard import publish_diagnostics_dashboard_states
from picot.addon.diagnostics_timeline import DiagnosticsTimeline
from picot.addon.diagnostics_timeline_dashboard import (
    publish_diagnostics_timeline_idle,
    publish_diagnostics_timeline_state,
)
from picot.addon.goodwe_dashboard import publish_goodwe_dashboard_states
from picot.addon.goodwe_observer import (
    DEFAULT_GOODWE_POWER_ENTITY,
    read_goodwe_observation,
    unavailable_goodwe_observation,
)
from picot.addon.history_store import HistoryStore
from picot.addon.plan_review import evaluate_plan_review, plan_review_log_event
from picot.addon.power_comparison import (
    add_power_comparison_fields,
    publish_power_comparison_states,
)
from picot.addon.pv_deviation_evaluator import (
    PvDeviationEvaluator,
    pv_deviation_evaluator_log_event,
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
    options: dict[str, Any], token: str, *, observed_at: datetime
) -> dict[str, object]:
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
            exc, observed_at=observed_at, power_entity=power_entity
        )


def _zendure_fields(
    options: dict[str, Any], token: str, *, observed_at: datetime
) -> dict[str, object]:
    power_entity = str(options.get("battery_power_entity", DEFAULT_ZENDURE_POWER_ENTITY))
    try:
        fields = read_zendure_observation(
            runtime._request_json,
            token,
            observed_at=observed_at,
            power_entity=power_entity,
        )
    except Exception as exc:
        return unavailable_zendure_observation(
            exc, observed_at=observed_at, power_entity=power_entity
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


def _run_price_planner_once(options: dict[str, Any], token: str) -> dict[str, object]:
    strategy = str(options.get("price_strategy", "v1"))
    if strategy == "v1":
        return runtime.run_planner_once(options, token)
    if strategy == "v2":
        return price_runtime_v2.run_planner_once(options, token)
    raise ValueError(f"Unsupported price_strategy: {strategy}")


def run_telemetry_once(
    options: dict[str, Any],
    token: str,
    planner_event: dict[str, object] | None,
    *,
    pv_deviation_evaluator: PvDeviationEvaluator | None = None,
    diagnostics_timeline: DiagnosticsTimeline | None = None,
) -> dict[str, object]:
    """Read and publish observation data even when no planner context exists."""

    observed_at = datetime.now(runtime.LOCAL_TIMEZONE)
    event = dict(planner_event or {})
    event["planner_context_status"] = "available" if planner_event is not None else "unavailable"
    event.update(runtime._grid_fields(options, token))
    event.update(runtime._solcast_fields(token, observed_at=observed_at))
    event.update(_goodwe_fields(options, token, observed_at=observed_at))
    event.update(_zendure_fields(options, token, observed_at=observed_at))
    event["telemetry_updated_at"] = observed_at.isoformat()
    event["telemetry_interval_seconds"] = int(options["telemetry_interval_seconds"])
    add_power_comparison_fields(event)
    add_pv_forecast_comparison_fields(event)
    if pv_deviation_evaluator is not None:
        event.update(pv_deviation_evaluator.evaluate(event))
    event.update(evaluate_plan_review(event))
    if diagnostics_timeline is not None:
        event.update(diagnostics_timeline.evaluate(event))
    publish_dashboard_states(event, token)
    publish_goodwe_dashboard_states(event, token)
    publish_zendure_dashboard_states(event, token)
    publish_power_comparison_states(event, token)
    publish_diagnostics_dashboard_states(event, token)
    publish_diagnostics_timeline_state(event, token)
    return event


def _p1_log_event(event: dict[str, object]) -> dict[str, object]:
    return {
        "event": "picot_p1_snapshot",
        "layer": "p1_grid",
        "status": event.get("p1_status"),
        "source_entity": event.get("p1_entity"),
        "error": event.get("p1_error"),
        "grid_power_w": event.get("grid_power_w"),
        "grid_import_w": event.get("grid_import_w"),
        "grid_export_w": event.get("grid_export_w"),
        "grid_direction": event.get("grid_direction"),
        "observed_at": event.get("p1_measured_at") or event.get("telemetry_updated_at"),
    }


def _goodwe_log_event(event: dict[str, object]) -> dict[str, object]:
    return {
        "event": "picot_goodwe_snapshot",
        "layer": "pv_actual",
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
    return {
        "event": "picot_zendure_snapshot",
        "layer": "battery",
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


def _timeline_log_event(event: dict[str, object]) -> dict[str, object] | None:
    timeline_event = event.get("diagnostics_timeline_event")
    if not isinstance(timeline_event, str) or not timeline_event:
        return None
    return {
        "event": "picot_diagnostics_timeline",
        "layer": "planner_timeline",
        "timeline_event": timeline_event,
        "rolling_deviation_percent": event.get(
            "diagnostics_timeline_rolling_deviation_percent"
        ),
        "evaluator_status": event.get("diagnostics_timeline_evaluator_status"),
        "plan_review_status": event.get(
            "diagnostics_timeline_plan_review_status"
        ),
        "plan_review_outcome": event.get(
            "diagnostics_timeline_plan_review_outcome"
        ),
        "plan_review_action": event.get(
            "diagnostics_timeline_plan_review_action"
        ),
        "control_change_allowed": event.get(
            "diagnostics_timeline_control_change_allowed"
        ),
        "observed_at": event.get("diagnostics_timeline_observed_at"),
    }


def _runtime_error_event(stream: str, exc: Exception) -> dict[str, object]:
    return {
        "event": "picot_runtime_error",
        "layer": stream,
        "stream": stream,
        "error": str(exc) or exc.__class__.__name__,
        "observed_at": datetime.now(runtime.LOCAL_TIMEZONE).isoformat(),
    }


def _log_and_persist(history: HistoryStore, event: dict[str, object]) -> None:
    """Write the same structured evidence to console and persistent history."""

    runtime._log_event(event)
    history.append(event)


def _log_error_and_persist(history: HistoryStore, stream: str, exc: Exception) -> None:
    _log_and_persist(history, _runtime_error_event(stream, exc))


def main() -> int:
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
    pv_deviation_evaluator = PvDeviationEvaluator()
    diagnostics_timeline = DiagnosticsTimeline()
    history = HistoryStore()

    print("PicoT HEMS add-on starting", flush=True)
    publish_diagnostics_timeline_idle(token)
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
                _log_and_persist(history, planner_event)
                scheduled_boundary = runtime._scheduled_boundary(
                    planner_event, now=wall_clock_now
                )
            except Exception as exc:
                _log_error_and_persist(history, "scheduled_transition", exc)

        if monotonic_now >= next_planner_run:
            try:
                planner_event = _run_price_planner_once(options, token)
                _log_and_persist(history, planner_event)
                scheduled_boundary = runtime._scheduled_boundary(
                    planner_event, now=wall_clock_now
                )
            except Exception as exc:
                _log_error_and_persist(history, "planner", exc)
            next_planner_run = monotonic_now + planner_interval

        if monotonic_now >= next_telemetry_run:
            try:
                telemetry_event = run_telemetry_once(
                    options,
                    token,
                    planner_event,
                    pv_deviation_evaluator=pv_deviation_evaluator,
                    diagnostics_timeline=diagnostics_timeline,
                )
                events = [
                    _p1_log_event(telemetry_event),
                    runtime._solcast_log_event(telemetry_event),
                    _goodwe_log_event(telemetry_event),
                    _zendure_log_event(telemetry_event),
                    pv_forecast_comparison_log_event(telemetry_event),
                    pv_deviation_evaluator_log_event(telemetry_event),
                    plan_review_log_event(telemetry_event),
                ]
                timeline_event = _timeline_log_event(telemetry_event)
                if timeline_event is not None:
                    events.append(timeline_event)
                for event in events:
                    _log_and_persist(history, event)
            except Exception as exc:
                _log_error_and_persist(history, "telemetry", exc)
            next_telemetry_run = monotonic_now + telemetry_interval

        time.sleep(runtime.SCHEDULER_TICK_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
