from __future__ import annotations

from picot.addon.power_comparison import (
    add_power_comparison_fields,
    power_comparison_dashboard_states,
)


def test_unavailable_inputs_publish_ha_safe_states() -> None:
    event: dict[str, object] = {
        "goodwe_solar_power_w": None,
        "grid_power_w": 125.0,
        "zendure_signed_power_w": -50.0,
        "telemetry_updated_at": "2026-08-12T23:21:56+02:00",
    }

    add_power_comparison_fields(event)
    states = power_comparison_dashboard_states(event)

    assert event["house_power_status"] == "unavailable"
    assert event["self_supply_power_status"] == "unavailable"
    assert states["sensor.picot_house_power"]["state"] == "unavailable"
    assert states["sensor.picot_self_supply_power"]["state"] == "unavailable"
