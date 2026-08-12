from __future__ import annotations

from picot.addon.power_comparison import (
    add_power_comparison_fields,
    power_comparison_dashboard_states,
)


def test_power_comparison_uses_unavailable_state_when_source_missing() -> None:
    event: dict[str, object] = {
        "goodwe_solar_power_w": None,
        "grid_power_w": 100.0,
        "zendure_signed_power_w": 0.0,
    }

    add_power_comparison_fields(event)
    states = power_comparison_dashboard_states(event)

    assert states["sensor.picot_house_power"]["state"] == "unavailable"
    assert states["sensor.picot_self_supply_power"]["state"] == "unavailable"
