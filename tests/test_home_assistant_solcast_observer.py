from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from picot.addon.solcast_observer import (
    SOLCAST_ENTITY_IDS,
    read_solcast_observation,
    unavailable_solcast_observation,
)

OBSERVED_AT = datetime(2026, 8, 2, 18, 30, tzinfo=UTC)


def _state(value: object, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"state": value, "attributes": attributes or {}}


def test_read_solcast_observation_normalizes_runtime_fields() -> None:
    states: dict[str, dict[str, Any]] = {
        "sensor.solcast_pv_forecast_voorspelling_vandaag": _state(
            25.7,
            {
                "estimate10": 22.3,
                "estimate90": 26.5,
                "analysis": {"confidence": 0.84},
                "detailedForecast": [
                    {
                        "period_start": "2026-08-02T18:30:00+02:00",
                        "pv_estimate": 0.8,
                        "pv_estimate10": 0.6,
                        "pv_estimate90": 0.9,
                    }
                ],
            },
        ),
        "sensor.solcast_pv_forecast_voorspelling_morgen": _state(
            23.7,
            {
                "estimate10": 15.7,
                "estimate90": 25.4,
                "analysis": {"confidence": 0.62},
                "detailedForecast": [
                    {
                        "period_start": "2026-08-03T12:00:00+02:00",
                        "pv_estimate": 2.7,
                        "pv_estimate10": 1.9,
                        "pv_estimate90": 2.8,
                    }
                ],
            },
        ),
        "sensor.solcast_pv_forecast_resterende_voorspelling_vandaag": _state(1.5),
        "sensor.solcast_pv_forecast_huidig_vermogen": _state(933),
        "sensor.solcast_pv_forecast_api_laatst_geraadpleegd": _state(
            "2026-08-02T16:23:59+00:00"
        ),
        "sensor.solcast_pv_forecast_api_gebruik": _state(10),
        "sensor.solcast_pv_forecast_api_limiet": _state(10),
    }

    def request_json(path: str, token: str) -> dict[str, Any]:
        assert token == "token"
        entity_id = path.removeprefix("/api/states/")
        assert entity_id in SOLCAST_ENTITY_IDS
        return states[entity_id]

    observation = read_solcast_observation(
        request_json,
        "token",
        observed_at=OBSERVED_AT,
    )

    assert observation["solcast_status"] == "available"
    assert observation["solcast_forecast_today_kwh"] == 25.7
    assert observation["solcast_forecast_tomorrow_kwh"] == 23.7
    assert observation["solcast_current_expected_power_w"] == 933.0
    assert observation["solcast_today_confidence"] == 0.84
    assert observation["solcast_forecast_point_count"] == 2


def test_unavailable_solcast_observation_keeps_failure_isolated() -> None:
    observation = unavailable_solcast_observation(
        RuntimeError("Solcast unavailable"),
        observed_at=OBSERVED_AT,
    )

    assert observation["solcast_status"] == "unavailable"
    assert observation["solcast_error"] == "Solcast unavailable"
    assert observation["solcast_forecast_today_kwh"] is None
    assert observation["solcast_forecast_point_count"] == 0
