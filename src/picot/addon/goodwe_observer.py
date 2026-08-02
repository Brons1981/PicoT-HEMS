"""Read selected GoodWe entities through Home Assistant without influencing planning."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant_goodwe import goodwe_snapshot_from_entities

GOODWE_ENTITY_IDS = (
    "sensor.0_energie_inverter_goodwe_solar_power",
    "sensor.0_energie_inverter_goodwe_generation_today",
    "sensor.0_energie_inverter_goodwe_generation_total",
    "sensor.0_energie_inverter_goodwe_temperature",
)

RequestJson = Callable[[str, str], dict[str, Any]]


def read_goodwe_observation(
    request_json: RequestJson,
    token: str,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return normalized dashboard fields from one atomic GoodWe snapshot."""

    states: dict[str, dict[str, Any]] = {}
    for entity_id in GOODWE_ENTITY_IDS:
        states[entity_id] = request_json(f"/api/states/{entity_id}", token)

    snapshot = goodwe_snapshot_from_entities(states, observed_at=observed_at)
    return {
        "goodwe_status": snapshot.status,
        "goodwe_source": snapshot.source,
        "goodwe_error": None,
        "goodwe_observed_at": snapshot.observed_at.isoformat(),
        "goodwe_solar_power_w": snapshot.solar_power_w,
        "goodwe_generation_today_kwh": snapshot.generation_today_kwh,
        "goodwe_generation_total_kwh": snapshot.generation_total_kwh,
        "goodwe_temperature_c": snapshot.temperature_c,
    }


def unavailable_goodwe_observation(
    error: Exception,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return an explicit unavailable observation without stopping PicoT."""

    return {
        "goodwe_status": "unavailable",
        "goodwe_source": "Home Assistant GoodWe SEMS API",
        "goodwe_error": str(error) or error.__class__.__name__,
        "goodwe_observed_at": observed_at.isoformat(),
        "goodwe_solar_power_w": None,
        "goodwe_generation_today_kwh": None,
        "goodwe_generation_total_kwh": None,
        "goodwe_temperature_c": None,
    }
