"""Normalize Home Assistant Solcast entities into a PicoT solar snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SolarForecastPoint:
    """One normalized Solcast forecast interval."""

    starts_at: datetime
    estimate_kw: float
    estimate10_kw: float
    estimate90_kw: float


@dataclass(frozen=True, slots=True)
class SolcastSnapshot:
    """Read-only Solcast observation for validation and future planning."""

    status: str
    source: str
    measured_at: datetime
    last_api_update: datetime
    forecast_today_kwh: float
    forecast_tomorrow_kwh: float
    remaining_today_kwh: float
    current_expected_power_w: float
    today_estimate10_kwh: float
    today_estimate90_kwh: float
    tomorrow_estimate10_kwh: float
    tomorrow_estimate90_kwh: float
    today_confidence: float | None
    tomorrow_confidence: float | None
    api_used: int
    api_limit: int
    forecast_points: tuple[SolarForecastPoint, ...]


class SolcastSnapshotError(ValueError):
    """Raised when required Solcast state cannot be normalized."""


def _parse_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise SolcastSnapshotError(f"{field} is not a timestamp.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SolcastSnapshotError(f"{field} must be timezone-aware.")
    return parsed


def _number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise SolcastSnapshotError(f"{field} is not numeric.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SolcastSnapshotError(f"{field} is not numeric.") from exc


def _entity(states: dict[str, dict[str, Any]], entity_id: str) -> dict[str, Any]:
    state = states.get(entity_id)
    if state is None:
        raise SolcastSnapshotError(f"Missing Solcast entity: {entity_id}.")
    if state.get("state") in {None, "unknown", "unavailable"}:
        raise SolcastSnapshotError(f"Solcast entity is unavailable: {entity_id}.")
    return state


def _attributes(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("attributes", {})
    if not isinstance(value, dict):
        raise SolcastSnapshotError("Solcast attributes are invalid.")
    return value


def _confidence(attributes: dict[str, Any]) -> float | None:
    analysis = attributes.get("analysis")
    if not isinstance(analysis, dict):
        return None
    value = analysis.get("confidence")
    return None if value is None else _number(value, "confidence")


def _forecast_points(*states: dict[str, Any]) -> tuple[SolarForecastPoint, ...]:
    points: list[SolarForecastPoint] = []
    for state in states:
        detailed = _attributes(state).get("detailedForecast", [])
        if not isinstance(detailed, list):
            raise SolcastSnapshotError("detailedForecast is not a list.")
        for item in detailed:
            if not isinstance(item, dict):
                continue
            points.append(
                SolarForecastPoint(
                    starts_at=_parse_datetime(item.get("period_start"), "period_start"),
                    estimate_kw=_number(item.get("pv_estimate"), "pv_estimate"),
                    estimate10_kw=_number(item.get("pv_estimate10"), "pv_estimate10"),
                    estimate90_kw=_number(item.get("pv_estimate90"), "pv_estimate90"),
                )
            )
    points.sort(key=lambda point: point.starts_at)
    return tuple(points)


def solcast_snapshot_from_entities(
    states: dict[str, dict[str, Any]],
    *,
    observed_at: datetime,
) -> SolcastSnapshot:
    """Build one atomic read-only snapshot from configured Solcast entities."""

    if observed_at.tzinfo is None:
        raise SolcastSnapshotError("observed_at must be timezone-aware.")

    today = _entity(states, "sensor.solcast_pv_forecast_voorspelling_vandaag")
    tomorrow = _entity(states, "sensor.solcast_pv_forecast_voorspelling_morgen")
    remaining = _entity(
        states,
        "sensor.solcast_pv_forecast_resterende_voorspelling_vandaag",
    )
    current_power = _entity(states, "sensor.solcast_pv_forecast_huidig_vermogen")
    last_update = _entity(states, "sensor.solcast_pv_forecast_api_laatst_geraadpleegd")
    api_used = _entity(states, "sensor.solcast_pv_forecast_api_gebruik")
    api_limit = _entity(states, "sensor.solcast_pv_forecast_api_limiet")

    today_attributes = _attributes(today)
    tomorrow_attributes = _attributes(tomorrow)
    return SolcastSnapshot(
        status="available",
        source="Home Assistant Solcast PV Forecast",
        measured_at=observed_at,
        last_api_update=_parse_datetime(last_update.get("state"), "last_api_update"),
        forecast_today_kwh=_number(today.get("state"), "forecast_today_kwh"),
        forecast_tomorrow_kwh=_number(tomorrow.get("state"), "forecast_tomorrow_kwh"),
        remaining_today_kwh=_number(remaining.get("state"), "remaining_today_kwh"),
        current_expected_power_w=_number(
            current_power.get("state"),
            "current_expected_power_w",
        ),
        today_estimate10_kwh=_number(
            today_attributes.get("estimate10"),
            "today_estimate10_kwh",
        ),
        today_estimate90_kwh=_number(
            today_attributes.get("estimate90"),
            "today_estimate90_kwh",
        ),
        tomorrow_estimate10_kwh=_number(
            tomorrow_attributes.get("estimate10"),
            "tomorrow_estimate10_kwh",
        ),
        tomorrow_estimate90_kwh=_number(
            tomorrow_attributes.get("estimate90"),
            "tomorrow_estimate90_kwh",
        ),
        today_confidence=_confidence(today_attributes),
        tomorrow_confidence=_confidence(tomorrow_attributes),
        api_used=int(_number(api_used.get("state"), "api_used")),
        api_limit=int(_number(api_limit.get("state"), "api_limit")),
        forecast_points=_forecast_points(today, tomorrow),
    )
