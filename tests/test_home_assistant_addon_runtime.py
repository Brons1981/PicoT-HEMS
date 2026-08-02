from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from picot.addon import runtime
from picot.addon.runtime import _desired_option, _price_forecast
from picot.domain.execution_primitive import ExecutionPrimitive

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def test_addon_maps_only_the_two_accepted_live_modes() -> None:
    assert (
        _desired_option(ExecutionPrimitive.BALANCE_DISCHARGE_ONLY)
        == "Alleen slim ontladen"
    )
    assert (
        _desired_option(ExecutionPrimitive.BALANCE_BIDIRECTIONAL)
        == "Nul op de meter"
    )


def test_addon_builds_price_forecast_from_nordpool_raw_points() -> None:
    state = {
        "entity_id": "sensor.nordpool_kwh_nl_eur_2_10_021",
        "attributes": {
            "raw_today": [
                {
                    "start": "2026-08-02T09:00:00+00:00",
                    "end": "2026-08-02T10:00:00+00:00",
                    "value": 0.21,
                },
                {
                    "start": "2026-08-02T10:00:00+00:00",
                    "end": "2026-08-02T11:00:00+00:00",
                    "value": 0.11,
                },
            ],
            "raw_tomorrow": [],
        },
    }

    forecast = _price_forecast(state, now=NOW)

    assert forecast.source == "sensor.nordpool_kwh_nl_eur_2_10_021"
    assert tuple(point.value for point in forecast.points) == (0.21, 0.11)
    assert forecast.expires_at == datetime(2026, 8, 2, 11, 0, tzinfo=UTC)


def test_telemetry_refresh_reuses_last_planner_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[dict[str, object]] = []

    def fake_grid_fields(
        options: dict[str, Any],
        token: str,
    ) -> dict[str, str | float | None]:
        assert options["p1_power_entity"] == "sensor.ct_shelly_pro_3em_api"
        assert token == "token"
        return {
            "p1_status": "available",
            "p1_entity": "sensor.ct_shelly_pro_3em_api",
            "p1_error": None,
            "grid_power_w": -1200.0,
            "grid_import_w": 0.0,
            "grid_export_w": 1200.0,
            "grid_direction": "export",
            "p1_measured_at": "2026-08-02T12:50:57+02:00",
        }

    def fake_publish(event: dict[str, object], token: str) -> None:
        assert token == "token"
        published.append(event)

    monkeypatch.setattr(runtime, "_grid_fields", fake_grid_fields)
    monkeypatch.setattr(runtime, "publish_dashboard_states", fake_publish)

    planner_event: dict[str, object] = {
        "event": "picot_price_decision",
        "evaluated_at": "2026-08-02T12:50:00+02:00",
        "mode": "live",
        "desired_option": "Nul op de meter",
    }
    options: dict[str, Any] = {
        "p1_power_entity": "sensor.ct_shelly_pro_3em_api",
        "telemetry_interval_seconds": 5,
    }

    event = runtime.run_telemetry_once(options, "token", planner_event)

    assert event["evaluated_at"] == planner_event["evaluated_at"]
    assert event["grid_power_w"] == -1200.0
    assert event["telemetry_interval_seconds"] == 5
    assert isinstance(event["telemetry_updated_at"], str)
    assert published == [event]
