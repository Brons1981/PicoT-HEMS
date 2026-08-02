"""Normalize Home Assistant GoodWe entities into a PicoT PV snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class GoodWeSnapshot:
    """Read-only GoodWe observation for validation and future planning."""

    status: str
    source: str
    observed_at: datetime
    solar_power_w: float
    generation_today_kwh: float
    generation_total_kwh: float
    temperature_c: float


class GoodWeSnapshotError(ValueError):
    """Raised when required GoodWe state cannot be normalized."""


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise GoodWeSnapshotError(f"{field} is not numeric.")
    try:
        return float(value)
    except ValueError as exc:
        raise GoodWeSnapshotError(f"{field} is not numeric.") from exc


def _entity(states: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    state = states.get(entity_id)
    if state is None:
        raise GoodWeSnapshotError(f"Missing GoodWe entity: {entity_id}.")
    if state.get("state") in {None, "unknown", "unavailable"}:
        raise GoodWeSnapshotError(f"GoodWe entity is unavailable: {entity_id}.")
    return state


def goodwe_snapshot_from_entities(
    states: dict[str, dict[str, Any]],
    *,
    observed_at: datetime,
) -> GoodWeSnapshot:
    """Build one atomic read-only snapshot from selected GoodWe entities."""

    if observed_at.tzinfo is None:
        raise GoodWeSnapshotError("observed_at must be timezone-aware.")

    solar_power = _entity(states, "sensor.0_energie_inverter_goodwe_solar_power")
    generation_today = _entity(
        states,
        "sensor.0_energie_inverter_goodwe_generation_today",
    )
    generation_total = _entity(
        states,
        "sensor.0_energie_inverter_goodwe_generation_total",
    )
    temperature = _entity(states, "sensor.0_energie_inverter_goodwe_temperature")

    return GoodWeSnapshot(
        status="available",
        source="Home Assistant GoodWe SEMS API",
        observed_at=observed_at,
        solar_power_w=_number(solar_power.get("state"), "solar_power_w"),
        generation_today_kwh=_number(
            generation_today.get("state"),
            "generation_today_kwh",
        ),
        generation_total_kwh=_number(
            generation_total.get("state"),
            "generation_total_kwh",
        ),
        temperature_c=_number(temperature.get("state"), "temperature_c"),
    )
