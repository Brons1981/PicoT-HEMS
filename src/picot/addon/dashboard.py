"""Publish structured PicoT runtime state for Home Assistant dashboards."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0

DashboardPayload = dict[str, object]
DashboardStates = dict[str, DashboardPayload]


def _power_attributes(
    friendly_name: str,
    icon: str,
    event: dict[str, object],
) -> dict[str, object]:
    return {
        "friendly_name": friendly_name,
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
        "icon": icon,
        "direction": event.get("grid_direction"),
        "measured_at": event.get("p1_measured_at"),
        "source_entity": event.get("p1_entity"),
        "source_status": event.get("p1_status"),
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }


def _text_attributes(
    friendly_name: str,
    icon: str,
    event: dict[str, object],
) -> dict[str, object]:
    return {
        "friendly_name": friendly_name,
        "icon": icon,
        "planner_evaluated_at": event.get("evaluated_at"),
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }


def _solcast_energy_attributes(
    friendly_name: str,
    event: dict[str, object],
) -> dict[str, object]:
    return {
        "friendly_name": friendly_name,
        "device_class": "energy",
        "state_class": "measurement",
        "unit_of_measurement": "kWh",
        "icon": "mdi:solar-power",
        "source": event.get("solcast_source"),
        "source_status": event.get("solcast_status"),
        "observed_at": event.get("solcast_observed_at"),
        "last_api_update": event.get("solcast_last_api_update"),
    }


def dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build the semantic HA states used by the technical cockpit."""

    status_attributes: dict[str, object] = {
        "friendly_name": "PicoT HEMS status",
        "icon": "mdi:home-lightning-bolt",
        "strategy": event.get("strategy", "Price Driven v1"),
        "current_option": event.get("current_option"),
        "desired_option": event.get("desired_option"),
        "reason": event.get("reason"),
        "window_starts_at": event.get("window_starts_at"),
        "window_ends_at": event.get("window_ends_at"),
        "dispatch_status": event.get("dispatch_status"),
        "last_planner_run": event.get("evaluated_at"),
        "last_telemetry_update": event.get("telemetry_updated_at"),
        "planner_interval_seconds": event.get("planner_interval_seconds"),
        "telemetry_interval_seconds": event.get("telemetry_interval_seconds"),
        "p1_status": event.get("p1_status"),
        "p1_entity": event.get("p1_entity"),
        "p1_error": event.get("p1_error"),
        "grid_direction": event.get("grid_direction"),
        "solcast_status": event.get("solcast_status"),
        "solcast_error": event.get("solcast_error"),
    }
    grid_attributes = _power_attributes(
        "PicoT netvermogen",
        "mdi:transmission-tower",
        event,
    )
    grid_attributes.update(
        {
            "import_w": event.get("grid_import_w"),
            "export_w": event.get("grid_export_w"),
        }
    )
    import_attributes = _power_attributes(
        "PicoT netimport",
        "mdi:transmission-tower-import",
        event,
    )
    export_attributes = _power_attributes(
        "PicoT netexport",
        "mdi:transmission-tower-export",
        event,
    )
    price_attributes: dict[str, object] = {
        "friendly_name": "PicoT actuele prijs",
        "state_class": "measurement",
        "unit_of_measurement": "EUR/kWh",
        "icon": "mdi:currency-eur",
        "selected_window_average": event.get("average_price_eur_per_kwh"),
        "window_starts_at": event.get("window_starts_at"),
        "window_ends_at": event.get("window_ends_at"),
        "planner_evaluated_at": event.get("evaluated_at"),
    }
    operating_mode_attributes = _text_attributes(
        "PicoT huidige modus",
        "mdi:battery-sync",
        event,
    )
    desired_mode_attributes = _text_attributes(
        "PicoT gewenste modus",
        "mdi:target",
        event,
    )
    dispatch_attributes = _text_attributes(
        "PicoT dispatchstatus",
        "mdi:call-made",
        event,
    )
    dispatch_attributes["reason"] = event.get("reason")
    window_attributes = _text_attributes(
        "PicoT actief prijsvenster",
        "mdi:timeline-clock",
        event,
    )
    window_attributes.update(
        {
            "starts_at": event.get("window_starts_at"),
            "ends_at": event.get("window_ends_at"),
            "average_price_eur_per_kwh": event.get("average_price_eur_per_kwh"),
        }
    )

    window_state = "inactive"
    if event.get("reason") == "The selected cheapest contiguous price window is active.":
        window_state = "active"

    solcast_status_attributes: dict[str, object] = {
        "friendly_name": "PicoT Solcast status",
        "icon": "mdi:weather-sunny-alert",
        "source": event.get("solcast_source"),
        "error": event.get("solcast_error"),
        "observed_at": event.get("solcast_observed_at"),
        "last_api_update": event.get("solcast_last_api_update"),
        "api_used": event.get("solcast_api_used"),
        "api_limit": event.get("solcast_api_limit"),
        "forecast_point_count": event.get("solcast_forecast_point_count"),
    }
    solcast_today_attributes = _solcast_energy_attributes(
        "PicoT Solcast vandaag",
        event,
    )
    solcast_today_attributes.update(
        {
            "estimate10_kwh": event.get("solcast_today_estimate10_kwh"),
            "estimate90_kwh": event.get("solcast_today_estimate90_kwh"),
            "confidence": event.get("solcast_today_confidence"),
            "detailedForecast": event.get("solcast_today_forecast_points", []),
        }
    )
    solcast_tomorrow_attributes = _solcast_energy_attributes(
        "PicoT Solcast morgen",
        event,
    )
    solcast_tomorrow_attributes.update(
        {
            "estimate10_kwh": event.get("solcast_tomorrow_estimate10_kwh"),
            "estimate90_kwh": event.get("solcast_tomorrow_estimate90_kwh"),
            "confidence": event.get("solcast_tomorrow_confidence"),
            "detailedForecast": event.get("solcast_tomorrow_forecast_points", []),
        }
    )
    solcast_remaining_attributes = _solcast_energy_attributes(
        "PicoT Solcast resterend vandaag",
        event,
    )
    today_forecast = event.get("solcast_today_forecast_points")
    tomorrow_forecast = event.get("solcast_tomorrow_forecast_points")
    combined_forecast = [
        *(today_forecast if isinstance(today_forecast, list) else []),
        *(tomorrow_forecast if isinstance(tomorrow_forecast, list) else []),
    ]
    solcast_power_attributes: dict[str, object] = {
        "friendly_name": "PicoT Solcast verwacht vermogen",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
        "icon": "mdi:solar-power-variant",
        "source": event.get("solcast_source"),
        "source_status": event.get("solcast_status"),
        "observed_at": event.get("solcast_observed_at"),
        "last_api_update": event.get("solcast_last_api_update"),
        "detailedForecast": combined_forecast,
    }
    solcast_confidence_attributes: dict[str, object] = {
        "friendly_name": "PicoT Solcast confidence",
        "state_class": "measurement",
        "unit_of_measurement": "%",
        "icon": "mdi:chart-bell-curve-cumulative",
        "tomorrow_confidence": event.get("solcast_tomorrow_confidence"),
        "source_status": event.get("solcast_status"),
        "observed_at": event.get("solcast_observed_at"),
    }
    today_confidence = event.get("solcast_today_confidence")
    confidence_percent: object = "unknown"
    if isinstance(today_confidence, (int, float)) and not isinstance(today_confidence, bool):
        confidence_percent = round(float(today_confidence) * 100.0, 1)

    return {
        "sensor.picot_hems_status": {
            "state": event.get("mode", "unknown"),
            "attributes": status_attributes,
        },
        "sensor.picot_grid_power": {
            "state": event.get("grid_power_w", "unknown"),
            "attributes": grid_attributes,
        },
        "sensor.picot_grid_import": {
            "state": event.get("grid_import_w", "unknown"),
            "attributes": import_attributes,
        },
        "sensor.picot_grid_export": {
            "state": event.get("grid_export_w", "unknown"),
            "attributes": export_attributes,
        },
        "sensor.picot_current_price": {
            "state": event.get("current_price_eur_per_kwh", "unknown"),
            "attributes": price_attributes,
        },
        "sensor.picot_operating_mode": {
            "state": event.get("current_option", "unknown"),
            "attributes": operating_mode_attributes,
        },
        "sensor.picot_desired_mode": {
            "state": event.get("desired_option", "unknown"),
            "attributes": desired_mode_attributes,
        },
        "sensor.picot_dispatch_status": {
            "state": event.get("dispatch_status", "unknown"),
            "attributes": dispatch_attributes,
        },
        "sensor.picot_active_price_window": {
            "state": window_state,
            "attributes": window_attributes,
        },
        "sensor.picot_solcast_status": {
            "state": event.get("solcast_status", "unknown"),
            "attributes": solcast_status_attributes,
        },
        "sensor.picot_solcast_today": {
            "state": event.get("solcast_forecast_today_kwh", "unknown"),
            "attributes": solcast_today_attributes,
        },
        "sensor.picot_solcast_tomorrow": {
            "state": event.get("solcast_forecast_tomorrow_kwh", "unknown"),
            "attributes": solcast_tomorrow_attributes,
        },
        "sensor.picot_solcast_remaining_today": {
            "state": event.get("solcast_remaining_today_kwh", "unknown"),
            "attributes": solcast_remaining_attributes,
        },
        "sensor.picot_solcast_expected_power": {
            "state": event.get("solcast_current_expected_power_w", "unknown"),
            "attributes": solcast_power_attributes,
        },
        "sensor.picot_solcast_confidence": {
            "state": confidence_percent,
            "attributes": solcast_confidence_attributes,
        },
        "sensor.picot_solcast_last_update": {
            "state": event.get("solcast_last_api_update", "unknown"),
            "attributes": {
                "friendly_name": "PicoT Solcast laatste update",
                "device_class": "timestamp",
                "icon": "mdi:update",
                "source_status": event.get("solcast_status"),
            },
        },
    }


def publish_dashboard_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish technical-cockpit entities through the Home Assistant REST API."""

    for entity_id, payload in dashboard_states(event).items():
        request = Request(
            f"{SUPERVISOR_BASE_URL}/api/states/{entity_id}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
        status = getattr(response, "status", None)
        if not isinstance(status, int) or status not in {200, 201}:
            raise RuntimeError(
                f"Home Assistant rejected dashboard state {entity_id}: {status}."
            )
