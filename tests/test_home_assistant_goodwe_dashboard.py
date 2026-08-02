from __future__ import annotations

from picot.addon.goodwe_dashboard import goodwe_dashboard_states


def test_goodwe_dashboard_states_expose_read_only_observation() -> None:
    event: dict[str, object] = {
        "goodwe_status": "available",
        "goodwe_source": "Home Assistant GoodWe SEMS API",
        "goodwe_error": None,
        "goodwe_observed_at": "2026-08-02T19:30:00+02:00",
        "goodwe_solar_power_w": 273.0,
        "goodwe_generation_today_kwh": 26.7,
        "goodwe_generation_total_kwh": 23349.1,
        "goodwe_temperature_c": 35.0,
    }

    states = goodwe_dashboard_states(event)

    assert states["sensor.picot_goodwe_status"]["state"] == "available"
    assert states["sensor.picot_goodwe_power"]["state"] == 273.0
    assert states["sensor.picot_goodwe_generation_today"]["state"] == 26.7
    assert states["sensor.picot_goodwe_generation_total"]["state"] == 23349.1
    assert states["sensor.picot_goodwe_temperature"]["state"] == 35.0

    power_attributes = states["sensor.picot_goodwe_power"]["attributes"]
    assert isinstance(power_attributes, dict)
    assert power_attributes["device_class"] == "power"
    assert power_attributes["source_status"] == "available"


def test_goodwe_dashboard_states_expose_unavailable_status() -> None:
    event: dict[str, object] = {
        "goodwe_status": "unavailable",
        "goodwe_source": "Home Assistant GoodWe SEMS API",
        "goodwe_error": "GoodWe unavailable",
        "goodwe_observed_at": "2026-08-02T19:30:00+02:00",
        "goodwe_solar_power_w": None,
        "goodwe_generation_today_kwh": None,
        "goodwe_generation_total_kwh": None,
        "goodwe_temperature_c": None,
    }

    states = goodwe_dashboard_states(event)

    assert states["sensor.picot_goodwe_status"]["state"] == "unavailable"
    assert states["sensor.picot_goodwe_power"]["state"] is None
