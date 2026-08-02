"""Publish structured PicoT runtime state for Home Assistant dashboards."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
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
