"""Build and publish the normalized power-comparison observation."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0


def _number(event: dict[str, object], key: str) -> float | None:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ha_state(value: object) -> object:
    """Return a Home Assistant-safe state value for optional measurements."""

    return "unavailable" if value is None else value


def add_power_comparison_fields(event: dict[str, object]) -> None:
    """Add derived house demand and self-supply without changing planner decisions."""

    pv_power_w = _number(event, "goodwe_solar_power_w")
    grid_power_w = _number(event, "grid_power_w")
    battery_power_w = _number(event, "zendure_signed_power_w")

    if pv_power_w is None or grid_power_w is None or battery_power_w is None:
        event["house_power_w"] = None
        event["house_power_status"] = "unavailable"
        event["self_supply_power_w"] = None
        event["self_supply_power_status"] = "unavailable"
        return

    # Sign contract:
    # grid: positive import, negative export
    # battery: positive charging, negative discharging
    # balance: PV + grid = house + battery
    house_power_w = pv_power_w + grid_power_w - battery_power_w
    grid_import_w = max(grid_power_w, 0.0)

    event["house_power_w"] = house_power_w
    event["house_power_status"] = "derived"
    event["self_supply_power_w"] = max(house_power_w - grid_import_w, 0.0)
    event["self_supply_power_status"] = "derived"


def _power_attributes(
    *,
    friendly_name: str,
    icon: str,
    event: dict[str, object],
    status_key: str,
    formula: str,
) -> dict[str, object]:
    return {
        "friendly_name": friendly_name,
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
        "icon": icon,
        "calculation_status": event.get(status_key),
        "formula": formula,
        "grid_sign": "positive_import_negative_export",
        "battery_sign": "positive_charge_negative_discharge",
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }


def power_comparison_dashboard_states(
    event: dict[str, object],
) -> dict[str, dict[str, object]]:
    """Return PicoT entities used by the power and energy-balance charts."""

    return {
        "sensor.picot_house_power": {
            "state": _ha_state(event.get("house_power_w", "unknown")),
            "attributes": _power_attributes(
                friendly_name="PicoT afgeleid huisverbruik",
                icon="mdi:home-lightning-bolt-outline",
                event=event,
                status_key="house_power_status",
                formula="pv_power_w + grid_power_w - battery_power_w",
            ),
        },
        "sensor.picot_self_supply_power": {
            "state": _ha_state(event.get("self_supply_power_w", "unknown")),
            "attributes": _power_attributes(
                friendly_name="PicoT zelfvoorzienend vermogen",
                icon="mdi:home-battery-outline",
                event=event,
                status_key="self_supply_power_status",
                formula="max(house_power_w - grid_import_w, 0)",
            ),
        },
    }


def publish_power_comparison_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish derived power-comparison entities through the HA REST API."""

    for entity_id, payload in power_comparison_dashboard_states(event).items():
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
                f"Home Assistant rejected power-comparison state {entity_id}: {status}."
            )
