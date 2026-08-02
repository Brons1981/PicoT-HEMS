"""Home Assistant add-on runtime for controlled live PicoT validation."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from picot.adapters.home_assistant import HomeAssistantAdapter, HomeAssistantDispatcher
from picot.adapters.home_assistant_household_state import (
    household_state_from_grid_power_entity,
)
from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.addon.dashboard import publish_dashboard_states
from picot.addon.solcast_observer import (
    read_solcast_observation,
    unavailable_solcast_observation,
)
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.home_assistant import HomeAssistantCommandMapping, HomeAssistantDispatchMode
from picot.planner.price_driven_strategy import PriceDrivenStrategy, PriceDrivenStrategyConfig

SUPERVISOR_BASE_URL = "http://supervisor/core"
OPTIONS_PATH = Path("/data/options.json")
LOCAL_TIMEZONE = ZoneInfo("Europe/Amsterdam")
SCHEDULER_TICK_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class ScheduledBoundary:
    """One exact start or end transition derived from the active price window."""

    occurs_at: datetime
    transition: str
    primitive: ExecutionPrimitive
    desired_option: str


def _request_json(path: str, token: str) -> dict[str, Any]:
    request = Request(
        f"{SUPERVISOR_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=10.0) as response:
        return cast(dict[str, Any], json.load(response))


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _price_forecast(state: dict[str, Any], *, now: datetime) -> ForecastSeries:
    attributes = cast(dict[str, Any], state.get("attributes", {}))
    raw_points: list[dict[str, Any]] = []
    for key in ("raw_today", "raw_tomorrow"):
        value = attributes.get(key, [])
        if isinstance(value, list):
            raw_points.extend(item for item in value if isinstance(item, dict))

    points: list[ForecastPoint] = []
    for item in raw_points:
        start_value = item.get("start")
        end_value = item.get("end")
        price_value = item.get("value", item.get("price"))
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            continue
        if not isinstance(price_value, (int, float)):
            continue
        points.append(
            ForecastPoint(
                starts_at=_parse_datetime(start_value),
                ends_at=_parse_datetime(end_value),
                value=float(price_value),
                confidence=1.0,
            )
        )

    points.sort(key=lambda point: point.starts_at)
    if not points:
        raise ValueError("Price entity has no usable raw_today/raw_tomorrow forecast points.")
    if points[-1].ends_at <= now:
        raise ValueError("Price entity has no forecast coverage after the current time.")
    return ForecastSeries(
        forecast_id=f"ha-price-{now.isoformat()}",
        kind=ForecastKind.ENERGY_PRICE,
        source=str(state.get("entity_id", "home-assistant")),
        created_at=now,
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=tuple(points),
    )


def _desired_option(primitive: ExecutionPrimitive) -> str:
    if primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY:
        return "Alleen slim ontladen"
    if primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL:
        return "Nul op de meter"
    raise ValueError(f"Unsupported live-validation primitive: {primitive.value}")


def _dispatch(
    *,
    primitive: ExecutionPrimitive,
    desired_option: str,
    target_entity: str,
    mode: HomeAssistantDispatchMode,
    token: str,
    now: datetime,
) -> str:
    request = ExecutionPrimitiveRequest(
        request_id=f"addon-request-{now.isoformat()}",
        plan_set_id=f"addon-plan-set-{now.date().isoformat()}",
        plan_id="price-driven-live-validation",
        plan_revision=1,
        segment_id=f"price-window-{now.isoformat()}",
        execution_scope_id="zendure-2400-ac",
        capability_id="zendure-operating-mode",
        primitive=primitive,
        requested_at=now,
    )
    mapping = HomeAssistantCommandMapping(
        mapping_id=f"ha-zendure-mode-{primitive.value}-v1",
        mapping_version=1,
        capability_id=request.capability_id,
        execution_scope_id=request.execution_scope_id,
        primitive=primitive,
        domain="input_select",
        service="select_option",
        entity_id=target_entity,
        value_key="option",
        fixed_value=desired_option,
    )
    call = HomeAssistantAdapter().translate(
        request,
        mapping,
        created_at=now,
        dispatch_mode=mode,
    )
    transport = None
    if mode is HomeAssistantDispatchMode.LIVE:
        transport = HomeAssistantHttpTransport(
            base_url=SUPERVISOR_BASE_URL,
            access_token=token,
            transport_mode=HomeAssistantDispatchMode.LIVE,
        )
    result = HomeAssistantDispatcher().dispatch(
        call,
        attempted_at=now,
        transport=transport,
    )
    return result.status.value


def _grid_fields(
    options: dict[str, Any],
    token: str,
) -> dict[str, str | float | None]:
    entity = str(options["p1_power_entity"])
    try:
        raw_state = _request_json(f"/api/states/{entity}", token)
        household = household_state_from_grid_power_entity(
            raw_state,
            import_is_positive=bool(options["p1_import_is_positive"]),
        )
    except Exception as exc:
        return {
            "p1_status": "unavailable",
            "p1_entity": entity,
            "p1_error": str(exc) or exc.__class__.__name__,
            "grid_power_w": None,
            "grid_import_w": None,
            "grid_export_w": None,
            "grid_direction": "unknown",
            "p1_measured_at": None,
        }

    grid_power_w = household.grid_power_w
    assert grid_power_w is not None
    if grid_power_w > 0:
        grid_direction = "import"
    elif grid_power_w < 0:
        grid_direction = "export"
    else:
        grid_direction = "balanced"

    return {
        "p1_status": "available",
        "p1_entity": entity,
        "p1_error": None,
        "grid_power_w": grid_power_w,
        "grid_import_w": max(0.0, grid_power_w),
        "grid_export_w": max(0.0, -grid_power_w),
        "grid_direction": grid_direction,
        "p1_measured_at": household.measured_at.isoformat(),
    }


def _solcast_fields(token: str, *, observed_at: datetime) -> dict[str, object]:
    """Read Solcast independently so a source failure cannot stop PicoT."""

    try:
        return read_solcast_observation(
            _request_json,
            token,
            observed_at=observed_at,
        )
    except Exception as exc:
        return unavailable_solcast_observation(exc, observed_at=observed_at)


def _scheduled_boundary(
    planner_event: dict[str, object],
    *,
    now: datetime,
) -> ScheduledBoundary | None:
    """Return the next future transition for the selected price window."""

    raw_start = planner_event.get("window_starts_at")
    raw_end = planner_event.get("window_ends_at")
    if not isinstance(raw_start, str) or not isinstance(raw_end, str):
        return None

    starts_at = _parse_datetime(raw_start)
    ends_at = _parse_datetime(raw_end)
    if now < starts_at:
        primitive = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
        return ScheduledBoundary(
            occurs_at=starts_at,
            transition="window_start",
            primitive=primitive,
            desired_option=_desired_option(primitive),
        )
    if now < ends_at:
        primitive = ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
        return ScheduledBoundary(
            occurs_at=ends_at,
            transition="window_end",
            primitive=primitive,
            desired_option=_desired_option(primitive),
        )
    return None


def run_scheduled_boundary_once(
    options: dict[str, Any],
    token: str,
    planner_event: dict[str, object],
    boundary: ScheduledBoundary,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Execute one planned transition without re-running the price planner."""

    executed_at = now or datetime.now(LOCAL_TIMEZONE)
    target_entity = str(options["target_entity"])
    mode = HomeAssistantDispatchMode(str(options["mode"]))
    target_state = _request_json(f"/api/states/{target_entity}", token)
    current_option = str(target_state.get("state", "unknown"))
    dispatch_status = "skipped_already_active"
    if current_option != boundary.desired_option:
        dispatch_status = _dispatch(
            primitive=boundary.primitive,
            desired_option=boundary.desired_option,
            target_entity=target_entity,
            mode=mode,
            token=token,
            now=executed_at,
        )

    event = dict(planner_event)
    event.update(
        {
            "event": "picot_scheduled_transition",
            "transition": boundary.transition,
            "scheduled_for": boundary.occurs_at.isoformat(),
            "executed_at": executed_at.isoformat(),
            "current_option": current_option,
            "desired_option": boundary.desired_option,
            "reason": "The scheduled price-window boundary was reached.",
            "dispatch_status": dispatch_status,
        }
    )
    return event


def run_planner_once(options: dict[str, Any], token: str) -> dict[str, object]:
    """Run the price planner and return a stable decision snapshot."""

    now = datetime.now(LOCAL_TIMEZONE)
    price_entity = str(options["price_entity"])
    target_entity = str(options["target_entity"])
    window_points = int(options["window_points"])
    mode = HomeAssistantDispatchMode(str(options["mode"]))

    price_state = _request_json(f"/api/states/{price_entity}", token)
    target_state = _request_json(f"/api/states/{target_entity}", token)
    forecast = _price_forecast(price_state, now=now)
    decision = PriceDrivenStrategy().evaluate(
        PriceDrivenStrategyConfig(window_points=window_points),
        forecast,
        evaluated_at=now,
    )
    if decision.primitive is None:
        raise RuntimeError("Price strategy returned no execution primitive.")

    desired_option = _desired_option(decision.primitive)
    current_option = str(target_state.get("state", "unknown"))
    dispatch_status = "skipped_already_active"
    if current_option != desired_option:
        dispatch_status = _dispatch(
            primitive=decision.primitive,
            desired_option=desired_option,
            target_entity=target_entity,
            mode=mode,
            token=token,
            now=now,
        )

    return {
        "event": "picot_price_decision",
        "evaluated_at": now.isoformat(),
        "mode": mode.value,
        "strategy": "Price Driven v1",
        "current_option": current_option,
        "desired_option": desired_option,
        "reason": decision.reason,
        "window_starts_at": decision.window_starts_at.isoformat()
        if decision.window_starts_at
        else None,
        "window_ends_at": decision.window_ends_at.isoformat()
        if decision.window_ends_at
        else None,
        "average_price_eur_per_kwh": decision.average_price_eur_per_kwh,
        "current_price_eur_per_kwh": decision.current_price_eur_per_kwh,
        "dispatch_status": dispatch_status,
        "planner_interval_seconds": int(options["planner_interval_seconds"]),
    }


def run_telemetry_once(
    options: dict[str, Any],
    token: str,
    planner_event: dict[str, object],
) -> dict[str, object]:
    """Refresh read-only observations without re-running or changing the plan."""

    observed_at = datetime.now(LOCAL_TIMEZONE)
    event = dict(planner_event)
    event.update(_grid_fields(options, token))
    event.update(_solcast_fields(token, observed_at=observed_at))
    event["telemetry_updated_at"] = observed_at.isoformat()
    event["telemetry_interval_seconds"] = int(options["telemetry_interval_seconds"])
    publish_dashboard_states(event, token)
    return event


def _solcast_log_event(event: dict[str, object]) -> dict[str, object]:
    """Return a compact dedicated log event for Solcast observation."""

    return {
        "event": "picot_solcast_snapshot",
        "status": event.get("solcast_status"),
        "error": event.get("solcast_error"),
        "forecast_today_kwh": event.get("solcast_forecast_today_kwh"),
        "forecast_tomorrow_kwh": event.get("solcast_forecast_tomorrow_kwh"),
        "remaining_today_kwh": event.get("solcast_remaining_today_kwh"),
        "expected_power_w": event.get("solcast_current_expected_power_w"),
        "today_confidence": event.get("solcast_today_confidence"),
        "tomorrow_confidence": event.get("solcast_tomorrow_confidence"),
        "api_used": event.get("solcast_api_used"),
        "api_limit": event.get("solcast_api_limit"),
        "observed_at": event.get("solcast_observed_at"),
        "last_api_update": event.get("solcast_last_api_update"),
    }


def _log_event(event: dict[str, object]) -> None:
    print(json.dumps(event, separators=(",", ":")), flush=True)


def _log_runtime_error(stream: str, exc: Exception) -> None:
    _log_event(
        {
            "event": "picot_runtime_error",
            "stream": stream,
            "error": str(exc) or exc.__class__.__name__,
        }
    )


def main() -> int:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN is unavailable; Home Assistant API access is required."
        )
    with OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))

    planner_interval = int(options["planner_interval_seconds"])
    telemetry_interval = int(options["telemetry_interval_seconds"])
    next_planner_run = 0.0
    next_telemetry_run = 0.0
    planner_event: dict[str, object] | None = None
    scheduled_boundary: ScheduledBoundary | None = None

    print("PicoT HEMS add-on starting", flush=True)
    while True:
        monotonic_now = time.monotonic()
        wall_clock_now = datetime.now(LOCAL_TIMEZONE)

        if scheduled_boundary is not None and wall_clock_now >= scheduled_boundary.occurs_at:
            try:
                assert planner_event is not None
                planner_event = run_scheduled_boundary_once(
                    options,
                    token,
                    planner_event,
                    scheduled_boundary,
                    now=wall_clock_now,
                )
                _log_event(planner_event)
                scheduled_boundary = _scheduled_boundary(
                    planner_event,
                    now=wall_clock_now,
                )
            except Exception as exc:
                _log_runtime_error("scheduled_transition", exc)

        if monotonic_now >= next_planner_run:
            try:
                planner_event = run_planner_once(options, token)
                _log_event(planner_event)
                scheduled_boundary = _scheduled_boundary(
                    planner_event,
                    now=wall_clock_now,
                )
            except Exception as exc:
                _log_runtime_error("planner", exc)
            next_planner_run = monotonic_now + planner_interval

        if planner_event is not None and monotonic_now >= next_telemetry_run:
            try:
                telemetry_event = run_telemetry_once(options, token, planner_event)
                _log_event(_solcast_log_event(telemetry_event))
            except Exception as exc:
                _log_runtime_error("telemetry", exc)
            next_telemetry_run = monotonic_now + telemetry_interval

        time.sleep(SCHEDULER_TICK_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
