from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from picot.addon.goodwe_observer import (
    GOODWE_ENTITY_IDS,
    read_goodwe_observation,
    unavailable_goodwe_observation,
)

OBSERVED_AT = datetime(2026, 8, 2, 19, 30, tzinfo=UTC)


def _state(value: object) -> dict[str, Any]:
    return {"state": value, "attributes": {}}


def test_read_goodwe_observation_normalizes_runtime_fields() -> None:
    states: dict[str, dict[str, Any]] = {
        "sensor.0_energie_inverter_goodwe_solar_power": _state(273),
        "sensor.0_energie_inverter_goodwe_generation_today": _state(26.7),
        "sensor.0_energie_inverter_goodwe_generation_total": _state(23349.1),
        "sensor.0_energie_inverter_goodwe_temperature": _state(35.0),
    }

    def request_json(path: str, token: str) -> dict[str, Any]:
        assert token == "token"
        entity_id = path.removeprefix("/api/states/")
        assert entity_id in GOODWE_ENTITY_IDS
        return states[entity_id]

    observation = read_goodwe_observation(
        request_json,
        "token",
        observed_at=OBSERVED_AT,
    )

    assert observation["goodwe_status"] == "available"
    assert observation["goodwe_solar_power_w"] == 273.0
    assert observation["goodwe_generation_today_kwh"] == 26.7
    assert observation["goodwe_generation_total_kwh"] == 23349.1
    assert observation["goodwe_temperature_c"] == 35.0
    assert observation["goodwe_observed_at"] == OBSERVED_AT.isoformat()


def test_unavailable_goodwe_observation_keeps_failure_isolated() -> None:
    observation = unavailable_goodwe_observation(
        RuntimeError("GoodWe unavailable"),
        observed_at=OBSERVED_AT,
    )

    assert observation["goodwe_status"] == "unavailable"
    assert observation["goodwe_error"] == "GoodWe unavailable"
    assert observation["goodwe_solar_power_w"] is None
    assert observation["goodwe_generation_today_kwh"] is None
