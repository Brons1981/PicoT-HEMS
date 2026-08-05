"""Read selected GoodWe entities directly through Home Assistant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant_goodwe import goodwe_snapshot_from_entities

DEFAULT_GOODWE_POWER_ENTITY = "sensor.inverter_54200dsn211r0265_vermogen"
GOODWE_GENERATION_TODAY_ENTITY = "sensor.inverter_54200dsn211r0265_energy_today"
GOODWE_GENERATION_TOTAL_ENTITY = "sensor.inverter_54200dsn211r0265_energie"
GOODWE_TEMPERATURE_ENTITY = "sensor.inverter_54200dsn211r0265_temperatuur"

RequestJson = Callable[[str, str], dict[str, Any]]


def goodwe_entity_ids(power_entity: str) -> tuple[str, str, str, str]:
    """Return the direct GoodWe source entities used for one observation."""

    return (
        power_entity,
        GOODWE_GENERATION_TODAY_ENTITY,
        GOODWE_GENERATION_TOTAL_ENTITY,
        GOODWE_TEMPERATURE_ENTITY,
    )


def read_goodwe_observation(
    request_json: RequestJson,
    token: str,
    *,
    observed_at: datetime,
    power_entity: str = DEFAULT_GOODWE_POWER_ENTITY,
) -> dict[str, object]:
    """Return normalized fields read directly from the configured HA sources."""

    states: dict[str, dict[str, Any]] = {}
    for entity_id in goodwe_entity_ids(power_entity):
        states[entity_id] = request_json(f"/api/states/{entity_id}", token)

    # The adapter currently expects the canonical GoodWe power key. Preserve that
    # internal contract while allowing the physical source entity to be configured.
    if power_entity != DEFAULT_GOODWE_POWER_ENTITY:
        states[DEFAULT_GOODWE_POWER_ENTITY] = states[power_entity]

    snapshot = goodwe_snapshot_from_entities(states, observed_at=observed_at)
    return {
        "goodwe_status": snapshot.status,
        "goodwe_source": snapshot.source,
        "goodwe_power_entity": power_entity,
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
    power_entity: str = DEFAULT_GOODWE_POWER_ENTITY,
) -> dict[str, object]:
    """Return an explicit unavailable observation without stopping PicoT."""

    return {
        "goodwe_status": "unavailable",
        "goodwe_source": "Home Assistant GoodWe SEMS API",
        "goodwe_power_entity": power_entity,
        "goodwe_error": str(error) or error.__class__.__name__,
        "goodwe_observed_at": observed_at.isoformat(),
        "goodwe_solar_power_w": None,
        "goodwe_generation_today_kwh": None,
        "goodwe_generation_total_kwh": None,
        "goodwe_temperature_c": None,
    }
