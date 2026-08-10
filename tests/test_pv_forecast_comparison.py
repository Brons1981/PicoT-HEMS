from picot.addon.pv_forecast_comparison import add_pv_forecast_comparison_fields


def test_compares_expected_solcast_power_with_actual_goodwe_power() -> None:
    event = {
        "solcast_status": "available",
        "goodwe_status": "available",
        "solcast_current_expected_power_w": 2685.0,
        "goodwe_solar_power_w": 2941.0,
    }

    add_pv_forecast_comparison_fields(event)

    assert event["pv_forecast_comparison_status"] == "available"
    assert event["pv_expected_power_w"] == 2685.0
    assert event["pv_actual_power_w"] == 2941.0
    assert event["pv_power_deviation_w"] == 256.0
    assert round(float(event["pv_power_deviation_percent"]), 3) == 9.534
    assert round(float(event["pv_actual_to_forecast_ratio"]), 3) == 1.095


def test_negative_deviation_is_preserved_for_underperformance() -> None:
    event = {
        "solcast_status": "available",
        "goodwe_status": "available",
        "solcast_current_expected_power_w": 3000.0,
        "goodwe_solar_power_w": 1800.0,
    }

    add_pv_forecast_comparison_fields(event)

    assert event["pv_power_deviation_w"] == -1200.0
    assert event["pv_power_deviation_percent"] == -40.0
    assert event["pv_actual_to_forecast_ratio"] == 0.6


def test_comparison_is_unavailable_when_a_source_is_unavailable() -> None:
    event = {
        "solcast_status": "unavailable",
        "goodwe_status": "available",
        "solcast_current_expected_power_w": None,
        "goodwe_solar_power_w": 1800.0,
    }

    add_pv_forecast_comparison_fields(event)

    assert event["pv_forecast_comparison_status"] == "unavailable"
    assert event["pv_power_deviation_w"] is None
    assert event["pv_power_deviation_percent"] is None


def test_zero_expected_power_does_not_invent_a_percentage() -> None:
    event = {
        "solcast_status": "available",
        "goodwe_status": "available",
        "solcast_current_expected_power_w": 0.0,
        "goodwe_solar_power_w": 100.0,
    }

    add_pv_forecast_comparison_fields(event)

    assert event["pv_power_deviation_w"] == 100.0
    assert event["pv_power_deviation_percent"] is None
    assert event["pv_actual_to_forecast_ratio"] is None
