"""Read Solcast entities through Home Assistant without influencing planning."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from picot.adapters.home_assistant_solcast import solcast_snapshot_from_entities

SOLCAST_ENTITY_IDS = (
    "sensor.solcast_pv_forecast_voorspelling_vandaag",
    "sensor.solcast_pv_forecast_voorspelling_morgen",
    "sensor.solcast_pv_forecast_resterende_voorspelling_vandaag",
    "sensor.solcast_pv_forecast_huidig_vermogen",
    "sensor.solcast_pv_forecast_api_laatst_geraadpleegd",
    "sensor.solcast_pv_forecast_api_gebruik",
    "sensor.solcast_pv_forecast_api_limiet",
)

RequestJson = Callable[[str, str], dict[str, Any]]


def read_solcast_observation(
    request_json: RequestJson,
    token: str,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return dashboard fields from one atomic read-only Solcast snapshot."""

    states: dict[str, dict[str, Any]] = {}
    for entity_id in SOLCAST_ENTITY_IDS:
        states[entity_id] = request_json(f"/api/states/{entity_id}", token)

    snapshot = solcast_snapshot_from_entities(states, observed_at=observed_at)
    return {
        "solcast_status": snapshot.status,
        "solcast_source": snapshot.source,
        "solcast_error": None,
        "solcast_observed_at": snapshot.measured_at.isoformat(),
        "solcast_last_api_update": snapshot.last_api_update.isoformat(),
        "solcast_forecast_today_kwh": snapshot.forecast_today_kwh,
        "solcast_forecast_tomorrow_kwh": snapshot.forecast_tomorrow_kwh,
        "solcast_remaining_today_kwh": snapshot.remaining_today_kwh,
        "solcast_current_expected_power_w": snapshot.current_expected_power_w,
        "solcast_today_estimate10_kwh": snapshot.today_estimate10_kwh,
        "solcast_today_estimate90_kwh": snapshot.today_estimate90_kwh,
        "solcast_tomorrow_estimate10_kwh": snapshot.tomorrow_estimate10_kwh,
        "solcast_tomorrow_estimate90_kwh": snapshot.tomorrow_estimate90_kwh,
        "solcast_today_confidence": snapshot.today_confidence,
        "solcast_tomorrow_confidence": snapshot.tomorrow_confidence,
        "solcast_api_used": snapshot.api_used,
        "solcast_api_limit": snapshot.api_limit,
        "solcast_forecast_point_count": len(snapshot.forecast_points),
    }


def unavailable_solcast_observation(
    error: Exception,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    """Return an explicit unavailable observation without stopping PicoT."""

    return {
        "solcast_status": "unavailable",
        "solcast_source": "Home Assistant Solcast PV Forecast",
        "solcast_error": str(error) or error.__class__.__name__,
        "solcast_observed_at": observed_at.isoformat(),
        "solcast_last_api_update": None,
        "solcast_forecast_today_kwh": None,
        "solcast_forecast_tomorrow_kwh": None,
        "solcast_remaining_today_kwh": None,
        "solcast_current_expected_power_w": None,
        "solcast_today_estimate10_kwh": None,
        "solcast_today_estimate90_kwh": None,
        "solcast_tomorrow_estimate10_kwh": None,
        "solcast_tomorrow_estimate90_kwh": None,
        "solcast_today_confidence": None,
        "solcast_tomorrow_confidence": None,
        "solcast_api_used": None,
        "solcast_api_limit": None,
        "solcast_forecast_point_count": 0,
    }
