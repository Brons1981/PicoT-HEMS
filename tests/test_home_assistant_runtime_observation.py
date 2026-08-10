from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from picot.addon import price_runtime_v2, runtime, runtime_observation

OBSERVED_AT = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)


def test_goodwe_fields_isolates_source_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_request(path: str, token: str) -> dict[str, Any]:
        raise RuntimeError("GoodWe unavailable")

    monkeypatch.setattr(runtime, "_request_json", failing_request)

    fields = runtime_observation._goodwe_fields(
        {"pv_power_entity": "sensor.test_pv"},
        "token",
        observed_at=OBSERVED_AT,
    )

    assert fields["goodwe_status"] == "unavailable"
    assert fields["goodwe_power_entity"] == "sensor.test_pv"
    assert fields["goodwe_error"] == "GoodWe unavailable"
    assert fields["goodwe_solar_power_w"] is None


def test_zendure_fields_isolates_source_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_request(path: str, token: str) -> dict[str, Any]:
        raise RuntimeError("Zendure unavailable")

    monkeypatch.setattr(runtime, "_request_json", failing_request)

    fields = runtime_observation._zendure_fields(
        {"battery_power_entity": "sensor.test_battery"},
        "token",
        observed_at=OBSERVED_AT,
    )

    assert fields["zendure_status"] == "unavailable"
    assert fields["zendure_power_entity"] == "sensor.test_battery"
    assert fields["zendure_error"] == "Zendure unavailable"
    assert fields["zendure_signed_power_w"] is None


def test_telemetry_publishes_combined_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published_main: list[dict[str, object]] = []
    published_goodwe: list[dict[str, object]] = []
    published_zendure: list[dict[str, object]] = []
    published_power: list[dict[str, object]] = []
    published_diagnostics: list[dict[str, object]] = []

    monkeypatch.setattr(
        runtime,
        "_grid_fields",
        lambda options, token: {"grid_power_w": -500.0},
    )
    monkeypatch.setattr(
        runtime,
        "_solcast_fields",
        lambda token, observed_at: {
            "solcast_status": "available",
            "solcast_current_expected_power_w": 1200.0,
        },
    )
    monkeypatch.setattr(
        runtime_observation,
        "_goodwe_fields",
        lambda options, token, observed_at: {
            "goodwe_status": "available",
            "goodwe_solar_power_w": 1100.0,
        },
    )
    monkeypatch.setattr(
        runtime_observation,
        "_zendure_fields",
        lambda options, token, observed_at: {
            "zendure_status": "available",
            "zendure_signed_power_w": -300.0,
        },
    )
    monkeypatch.setattr(
        runtime_observation,
        "publish_dashboard_states",
        lambda event, token: published_main.append(event),
    )
    monkeypatch.setattr(
        runtime_observation,
        "publish_goodwe_dashboard_states",
        lambda event, token: published_goodwe.append(event),
    )
    monkeypatch.setattr(
        runtime_observation,
        "publish_zendure_dashboard_states",
        lambda event, token: published_zendure.append(event),
    )
    monkeypatch.setattr(
        runtime_observation,
        "publish_power_comparison_states",
        lambda event, token: published_power.append(event),
    )
    monkeypatch.setattr(
        runtime_observation,
        "publish_diagnostics_dashboard_states",
        lambda event, token: published_diagnostics.append(event),
    )

    event = runtime_observation.run_telemetry_once(
        {
            "telemetry_interval_seconds": 5,
            "pv_power_entity": "sensor.test_pv",
            "battery_power_entity": "sensor.test_battery",
            "battery_charge_is_positive": True,
        },
        "token",
        {"event": "picot_price_decision"},
    )

    assert event["grid_power_w"] == -500.0
    assert event["solcast_current_expected_power_w"] == 1200.0
    assert event["goodwe_solar_power_w"] == 1100.0
    assert event["zendure_signed_power_w"] == -300.0
    assert event["house_power_w"] == 900.0
    assert event["house_power_status"] == "derived"
    assert event["self_supply_power_w"] == 900.0
    assert event["self_supply_power_status"] == "derived"
    assert published_main == [event]
    assert published_goodwe == [event]
    assert published_zendure == [event]
    assert published_power == [event]
    assert published_diagnostics == [event]


def test_goodwe_log_event_is_compact() -> None:
    event = runtime_observation._goodwe_log_event(
        {
            "goodwe_status": "available",
            "goodwe_power_entity": "sensor.test_pv",
            "goodwe_error": None,
            "goodwe_solar_power_w": 273.0,
            "goodwe_generation_today_kwh": 26.7,
            "goodwe_generation_total_kwh": 23349.1,
            "goodwe_temperature_c": 35.0,
            "goodwe_observed_at": "2026-08-02T20:00:00+02:00",
        }
    )

    assert event["event"] == "picot_goodwe_snapshot"
    assert event["source_entity"] == "sensor.test_pv"
    assert event["solar_power_w"] == 273.0
    assert event["generation_today_kwh"] == 26.7


def test_zendure_log_event_is_compact() -> None:
    event = runtime_observation._zendure_log_event(
        {
            "zendure_status": "available",
            "zendure_power_entity": "sensor.test_battery",
            "zendure_error": None,
            "zendure_soc_percent": 63.0,
            "zendure_actual_mode": "Ontladen",
            "zendure_requested_mode": "Nul op de meter",
            "zendure_signed_power_w": -812.0,
            "zendure_charge_power_w": 0.0,
            "zendure_discharge_power_w": 812.0,
            "zendure_power_consistent": True,
            "zendure_observed_at": "2026-08-02T20:45:15+02:00",
        }
    )

    assert event["event"] == "picot_zendure_snapshot"
    assert event["source_entity"] == "sensor.test_battery"
    assert event["signed_power_w"] == -812.0
    assert event["power_consistent"] is True


def test_price_strategy_defaults_to_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime,
        "run_planner_once",
        lambda options, token: {"strategy": "Price Driven v1"},
    )

    event = runtime_observation._run_price_planner_once({}, "token")

    assert event["strategy"] == "Price Driven v1"


def test_price_strategy_routes_to_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        price_runtime_v2,
        "run_planner_once",
        lambda options, token: {"strategy": "Price Driven v2"},
    )

    event = runtime_observation._run_price_planner_once(
        {"price_strategy": "v2"},
        "token",
    )

    assert event["strategy"] == "Price Driven v2"


def test_price_strategy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="Unsupported price_strategy"):
        runtime_observation._run_price_planner_once(
            {"price_strategy": "v3"},
            "token",
        )
