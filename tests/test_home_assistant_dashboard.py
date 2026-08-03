from __future__ import annotations

from picot.addon.dashboard import dashboard_states


def test_dashboard_states_expose_runtime_price_grid_and_solcast_data() -> None:
    event: dict[str, object] = {
        "mode": "live",
        "strategy": "Price Driven v1",
        "current_option": "Nul op de meter",
        "desired_option": "Nul op de meter",
        "reason": "The selected cheapest contiguous price window is active.",
        "window_starts_at": "2026-08-02T10:30:00+02:00",
        "window_ends_at": "2026-08-02T16:30:00+02:00",
        "dispatch_status": "skipped_already_active",
        "evaluated_at": "2026-08-02T12:50:59+02:00",
        "telemetry_updated_at": "2026-08-02T12:51:04+02:00",
        "planner_interval_seconds": 60,
        "telemetry_interval_seconds": 5,
        "p1_status": "available",
        "p1_entity": "sensor.ct_shelly_pro_3em_api",
        "p1_error": None,
        "grid_power_w": -1385.223,
        "grid_import_w": 0.0,
        "grid_export_w": 1385.223,
        "grid_direction": "export",
        "p1_measured_at": "2026-08-02T12:50:57+02:00",
        "current_price_eur_per_kwh": 0.104,
        "average_price_eur_per_kwh": 0.106,
        "solcast_status": "available",
        "solcast_source": "Home Assistant Solcast PV Forecast",
        "solcast_error": None,
        "solcast_observed_at": "2026-08-02T12:51:04+02:00",
        "solcast_last_api_update": "2026-08-02T10:23:59+00:00",
        "solcast_forecast_today_kwh": 25.7,
        "solcast_forecast_tomorrow_kwh": 23.7,
        "solcast_remaining_today_kwh": 1.5,
        "solcast_current_expected_power_w": 933.0,
        "solcast_today_estimate10_kwh": 22.3,
        "solcast_today_estimate90_kwh": 26.5,
        "solcast_tomorrow_estimate10_kwh": 15.7,
        "solcast_tomorrow_estimate90_kwh": 25.4,
        "solcast_today_confidence": 0.84,
        "solcast_tomorrow_confidence": 0.62,
        "solcast_api_used": 10,
        "solcast_api_limit": 10,
        "solcast_forecast_point_count": 2,
        "solcast_today_forecast_points": [
            {
                "period_start": "2026-08-02T18:30:00+02:00",
                "pv_estimate": 0.8,
                "pv_estimate10": 0.6,
                "pv_estimate90": 0.9,
            }
        ],
        "solcast_tomorrow_forecast_points": [
            {
                "period_start": "2026-08-03T12:00:00+02:00",
                "pv_estimate": 2.7,
                "pv_estimate10": 1.9,
                "pv_estimate90": 2.8,
            }
        ],
    }

    states = dashboard_states(event)

    assert states["sensor.picot_hems_status"]["state"] == "live"
    assert states["sensor.picot_grid_power"]["state"] == -1385.223
    assert states["sensor.picot_grid_import"]["state"] == 0.0
    assert states["sensor.picot_grid_export"]["state"] == 1385.223
    assert states["sensor.picot_current_price"]["state"] == 0.104
    assert states["sensor.picot_operating_mode"]["state"] == "Nul op de meter"
    assert states["sensor.picot_desired_mode"]["state"] == "Nul op de meter"
    assert states["sensor.picot_dispatch_status"]["state"] == "skipped_already_active"
    assert states["sensor.picot_active_price_window"]["state"] == "active"
    assert states["sensor.picot_solcast_status"]["state"] == "available"
    assert states["sensor.picot_solcast_today"]["state"] == 25.7
    assert states["sensor.picot_solcast_tomorrow"]["state"] == 23.7
    assert states["sensor.picot_solcast_remaining_today"]["state"] == 1.5
    assert states["sensor.picot_solcast_expected_power"]["state"] == 933.0
    assert states["sensor.picot_solcast_confidence"]["state"] == 84.0
    assert states["sensor.picot_solcast_last_update"]["state"] == "2026-08-02T10:23:59+00:00"

    status_attributes = states["sensor.picot_hems_status"]["attributes"]
    assert isinstance(status_attributes, dict)
    assert status_attributes["desired_option"] == "Nul op de meter"
    assert status_attributes["planner_interval_seconds"] == 60
    assert status_attributes["telemetry_interval_seconds"] == 5
    assert status_attributes["solcast_status"] == "available"

    grid_attributes = states["sensor.picot_grid_power"]["attributes"]
    assert isinstance(grid_attributes, dict)
    assert grid_attributes["direction"] == "export"
    assert grid_attributes["source_entity"] == "sensor.ct_shelly_pro_3em_api"

    window_attributes = states["sensor.picot_active_price_window"]["attributes"]
    assert isinstance(window_attributes, dict)
    assert window_attributes["starts_at"] == "2026-08-02T10:30:00+02:00"
    assert window_attributes["ends_at"] == "2026-08-02T16:30:00+02:00"

    today_attributes = states["sensor.picot_solcast_today"]["attributes"]
    assert isinstance(today_attributes, dict)
    assert today_attributes["estimate10_kwh"] == 22.3
    assert today_attributes["estimate90_kwh"] == 26.5
    assert today_attributes["confidence"] == 0.84
    assert today_attributes["detailedForecast"] == event["solcast_today_forecast_points"]

    tomorrow_attributes = states["sensor.picot_solcast_tomorrow"]["attributes"]
    assert isinstance(tomorrow_attributes, dict)
    assert tomorrow_attributes["detailedForecast"] == event["solcast_tomorrow_forecast_points"]


def test_dashboard_states_keep_solcast_unavailable_explicit() -> None:
    states = dashboard_states(
        {
            "solcast_status": "unavailable",
            "solcast_error": "Solcast unavailable",
        }
    )

    assert states["sensor.picot_solcast_status"]["state"] == "unavailable"
    assert states["sensor.picot_solcast_today"]["state"] == "unknown"
    assert states["sensor.picot_solcast_confidence"]["state"] == "unknown"

    attributes = states["sensor.picot_solcast_status"]["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["error"] == "Solcast unavailable"

    today_attributes = states["sensor.picot_solcast_today"]["attributes"]
    assert isinstance(today_attributes, dict)
    assert today_attributes["detailedForecast"] == []
