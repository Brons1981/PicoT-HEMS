"""Publish normalized GoodWe observations as PicoT Home Assistant sensors."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0

DashboardPayload = dict[str, object]
DashboardStates = dict[str, DashboardPayload]


def _measurement_attributes(
    friendly_name: str,
    icon: str,
    unit: str,
    event: dict[str, object],
    *,
    device_class: str | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "friendly_name": friendly_name,
        "icon": icon,
        "state_class": "measurement",
        "unit_of_measurement": unit,
        "source": event.get("goodwe_source"),
        "source_status": event.get("goodwe_status"),
        "source_error": event.get("goodwe_error"),
        "observed_at": event.get("goodwe_observed_at"),
    }
    if device_class is not None:
        attributes["device_class"] = device_class
    return attributes


def goodwe_dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build semantic PicoT states for the read-only GoodWe observation."""

    common_status_attributes: dict[str, object] = {
        "friendly_name": "PicoT GoodWe status",
        "icon": "mdi:solar-power-variant",
        "source": event.get("goodwe_source"),
        "error": event.get("goodwe_error"),
        "observed_at": event.get("goodwe_observed_at"),
    }
    return {
        "sensor.picot_goodwe_status": {
            "state": event.get("goodwe_status", "unknown"),
            "attributes": common_status_attributes,
        },
        "sensor.picot_goodwe_power": {
            "state": event.get("goodwe_solar_power_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT GoodWe PV-vermogen",
                "mdi:solar-power",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_goodwe_generation_today": {
            "state": event.get("goodwe_generation_today_kwh", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT GoodWe opbrengst vandaag",
                "mdi:solar-panel-large",
                "kWh",
                event,
                device_class="energy",
            ),
        },
        "sensor.picot_goodwe_generation_total": {
            "state": event.get("goodwe_generation_total_kwh", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT GoodWe totale opbrengst",
                "mdi:counter",
                "kWh",
                event,
                device_class="energy",
            ),
        },
        "sensor.picot_goodwe_temperature": {
            "state": event.get("goodwe_temperature_c", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT GoodWe temperatuur",
                "mdi:thermometer",
                "°C",
                event,
                device_class="temperature",
            ),
        },
    }


def publish_goodwe_dashboard_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish GoodWe observation sensors through the Home Assistant REST API."""

    for entity_id, payload in goodwe_dashboard_states(event).items():
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
                f"Home Assistant rejected GoodWe dashboard state {entity_id}: {status}."
            )
