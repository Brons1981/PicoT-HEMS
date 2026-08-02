from __future__ import annotations

from picot.addon.dashboard import dashboard_states


def test_dashboard_states_expose_runtime_price_and_grid_data() -> None:
    event: dict[str, object] = {
        "mode": "live",
        "current_option": "Nul op de meter",
        "desired_option": "Nul op de meter",
        "reason": "The selected cheapest contiguous price window is active.",
        "window_starts_at": "2026-08-02T10:30:00+02:00",
        "window_ends_at": "2026-08-02T16:30:00+02:00",
        "dispatch_status": "skipped_already_active",
        "evaluated_at": "2026-08-02T12:50:59+02:00",
        "p1_status": "available",
        "p1_entity": "sensor.ct_shelly_pro_3em_api",
        "grid_power_w": -1385.223,
        "grid_import_w": 0.0,
        "grid_export_w": 1385.223,
        "grid_direction": "export",
        "p1_measured_at": "2026-08-02T12:50:57+02:00",
        "current_price_eur_per_kwh": 0.104,
        "average_price_eur_per_kwh": 0.106,
    }

    states = dashboard_states(event)

    assert states["sensor.picot_hems_status"]["state"] == "live"
    assert states["sensor.picot_grid_power"]["state"] == -1385.223
    assert states["sensor.picot_current_price"]["state"] == 0.104

    status_attributes = states["sensor.picot_hems_status"]["attributes"]
    assert isinstance(status_attributes, dict)
    assert status_attributes["desired_option"] == "Nul op de meter"

    grid_attributes = states["sensor.picot_grid_power"]["attributes"]
    assert isinstance(grid_attributes, dict)
    assert grid_attributes["direction"] == "export"
    assert grid_attributes["source_entity"] == "sensor.ct_shelly_pro_3em_api"
