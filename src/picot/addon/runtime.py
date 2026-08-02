"""Minimal Home Assistant add-on runtime for the first live PicoT validation."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from picot.adapters.home_assistant import HomeAssistantAdapter, HomeAssistantDispatcher
from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.home_assistant import HomeAssistantCommandMapping, HomeAssistantDispatchMode
from picot.planner.price_driven_strategy import PriceDrivenStrategy, PriceDrivenStrategyConfig

SUPERVISOR_BASE_URL = "http://supervisor/core"
OPTIONS_PATH = Path("/data/options.json")
LOCAL_TIMEZONE = ZoneInfo("Europe/Amsterdam")


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
        starts_at = _parse_datetime(start_value)
        ends_at = _parse_datetime(end_value)
        points.append(
            ForecastPoint(
                starts_at=starts_at,
                ends_at=ends_at,
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


def run_once(options: dict[str, Any], token: str) -> None:
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

    print(
        json.dumps(
            {
                "event": "picot_price_decision",
                "evaluated_at": now.isoformat(),
                "mode": mode.value,
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
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def main() -> int:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN is unavailable; Home Assistant API access is required."
        )
    with OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))

    interval_seconds = int(options["interval_seconds"])
    print("PicoT HEMS add-on starting", flush=True)
    while True:
        try:
            run_once(options, token)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_runtime_error",
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
