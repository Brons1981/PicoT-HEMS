"""Publish normalized Zendure observations as PicoT Home Assistant sensors."""

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
        "source": event.get("zendure_source"),
        "source_status": event.get("zendure_status"),
        "source_error": event.get("zendure_error"),
        "observed_at": event.get("zendure_observed_at"),
        "power_consistent": event.get("zendure_power_consistent"),
    }
    if device_class is not None:
        attributes["device_class"] = device_class
    return attributes


def zendure_dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build semantic PicoT states for the read-only Zendure observation."""

    common = {
        "source": event.get("zendure_source"),
        "source_status": event.get("zendure_status"),
        "source_error": event.get("zendure_error"),
        "observed_at": event.get("zendure_observed_at"),
        "power_consistent": event.get("zendure_power_consistent"),
    }
    return {
        "sensor.picot_zendure_status": {
            "state": event.get("zendure_status", "unknown"),
            "attributes": {
                **common,
                "friendly_name": "PicoT Zendure status",
                "icon": "mdi:battery-heart-variant",
                "error_status": event.get("zendure_error_status"),
            },
        },
        "sensor.picot_zendure_soc": {
            "state": event.get("zendure_soc_percent", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure laadpercentage",
                "mdi:battery",
                "%",
                event,
                device_class="battery",
            ),
        },
        "sensor.picot_zendure_actual_mode": {
            "state": event.get("zendure_actual_mode", "unknown"),
            "attributes": {
                **common,
                "friendly_name": "PicoT Zendure werkelijke modus",
                "icon": "mdi:battery-sync",
            },
        },
        "sensor.picot_zendure_requested_mode": {
            "state": event.get("zendure_requested_mode", "unknown"),
            "attributes": {
                **common,
                "friendly_name": "PicoT Zendure aangevraagde modus",
                "icon": "mdi:battery-arrow-up-outline",
            },
        },
        "sensor.picot_zendure_power": {
            "state": event.get("zendure_signed_power_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure batterijvermogen",
                "mdi:battery-charging-medium",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_zendure_charge_power": {
            "state": event.get("zendure_charge_power_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure laadvermogen",
                "mdi:battery-plus-variant",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_zendure_discharge_power": {
            "state": event.get("zendure_discharge_power_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure ontlaadvermogen",
                "mdi:battery-minus-variant",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_zendure_power_to_house": {
            "state": event.get("zendure_power_to_house_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure vermogen naar huis",
                "mdi:home-import-outline",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_zendure_power_from_house": {
            "state": event.get("zendure_power_from_house_w", "unknown"),
            "attributes": _measurement_attributes(
                "PicoT Zendure vermogen van huis",
                "mdi:home-export-outline",
                "W",
                event,
                device_class="power",
            ),
        },
        "sensor.picot_zendure_soc_limit": {
            "state": event.get("zendure_soc_limit_status", "unknown"),
            "attributes": {
                **common,
                "friendly_name": "PicoT Zendure SoC-limiet",
                "icon": "mdi:battery-lock",
            },
        },
        "sensor.picot_zendure_error": {
            "state": event.get("zendure_error_status", "unknown"),
            "attributes": {
                **common,
                "friendly_name": "PicoT Zendure foutstatus",
                "icon": "mdi:battery-alert-variant-outline",
            },
        },
    }


def publish_zendure_dashboard_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish Zendure observation sensors through the Home Assistant REST API."""

    for entity_id, payload in zendure_dashboard_states(event).items():
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
                f"Home Assistant rejected Zendure dashboard state {entity_id}: {status}."
            )
