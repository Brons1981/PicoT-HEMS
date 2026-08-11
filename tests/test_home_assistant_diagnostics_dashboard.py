from __future__ import annotations

from picot.addon.diagnostics_dashboard import diagnostics_dashboard_states


def test_diagnostics_dashboard_exposes_replan_and_review_evidence() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-10T15:56:48+02:00",
        "pv_forecast_comparison_status": "available",
        "pv_expected_power_w": 2031.0,
        "pv_actual_power_w": 0.0,
        "pv_power_deviation_w": -2031.0,
        "pv_power_deviation_percent": -100.0,
        "pv_deviation_evaluator_status": "persistent_under_forecast",
        "pv_rolling_deviation_percent": -25.13,
        "pv_deviation_threshold_percent": 25.0,
        "pv_deviation_window_seconds": 900.0,
        "pv_deviation_minimum_history_seconds": 600.0,
        "pv_deviation_history_seconds": 896.6,
        "pv_deviation_sample_count": 178,
        "pv_deviation_replan_candidate": True,
        "plan_review_status": "completed",
        "plan_review_outcome": "current_plan_still_feasible",
        "plan_review_action": "keep_current_plan",
        "plan_review_trigger": "pv_deviation_replan_candidate",
        "plan_review_feasibility_scope": "phase1_observation_only",
        "plan_review_control_change_allowed": False,
        "plan_review_limitation": "Phase 1 observation only",
        "plan_review_grid_import_w": 0.0,
        "plan_review_grid_export_w": 4.9,
        "plan_review_battery_soc_percent": 98.0,
        "plan_review_battery_charge_power_w": 0.0,
        "plan_review_battery_discharge_power_w": 218.0,
        "pv_energy_15m_status": "available",
        "pv_energy_15m_expected_kwh": 0.52,
        "pv_energy_15m_actual_kwh": 0.49,
        "pv_energy_15m_deviation_percent": -5.77,
        "pv_energy_15m_coverage_seconds": 900.0,
        "pv_energy_30m_status": "available",
        "pv_energy_30m_expected_kwh": 1.02,
        "pv_energy_30m_actual_kwh": 1.00,
        "pv_energy_30m_deviation_percent": -1.96,
        "pv_energy_30m_coverage_seconds": 1800.0,
        "pv_energy_60m_status": "available",
        "pv_energy_60m_expected_kwh": 2.01,
        "pv_energy_60m_actual_kwh": 1.98,
        "pv_energy_60m_deviation_percent": -1.49,
        "pv_energy_60m_coverage_seconds": 3600.0,
    }

    states = diagnostics_dashboard_states(event)

    assert states["sensor.picot_pv_deviation_current"]["state"] == -100.0
    assert states["sensor.picot_pv_deviation_rolling"]["state"] == -25.13
    assert states["binary_sensor.picot_replan_candidate"]["state"] == "on"
    assert states["sensor.picot_plan_review_status"]["state"] == "completed"
    assert (
        states["binary_sensor.picot_plan_review_control_change_allowed"]["state"]
        == "off"
    )

    review_attributes = states["sensor.picot_plan_review_status"]["attributes"]
    assert isinstance(review_attributes, dict)
    assert review_attributes["outcome"] == "current_plan_still_feasible"
    assert review_attributes["action"] == "keep_current_plan"
    assert review_attributes["grid_export_w"] == 4.9
    assert review_attributes["battery_soc_percent"] == 98.0

    energy_state = states["sensor.picot_pv_energy_deviation_30m"]
    assert energy_state["state"] == -1.96
    energy_attributes = energy_state["attributes"]
    assert isinstance(energy_attributes, dict)
    assert energy_attributes["solcast_expected_kwh"] == 1.02
    assert energy_attributes["goodwe_actual_kwh"] == 1.00
    assert energy_attributes["observation_only"] is True
    assert energy_attributes["replan_input"] is False


def test_diagnostics_dashboard_exposes_recovery_state() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-10T16:15:13+02:00",
        "pv_power_deviation_percent": 12.0,
        "pv_rolling_deviation_percent": -24.90,
        "pv_deviation_evaluator_status": "within_tolerance",
        "pv_deviation_threshold_percent": 25.0,
        "pv_deviation_replan_candidate": False,
        "plan_review_status": "not_requested",
        "plan_review_control_change_allowed": False,
    }

    states = diagnostics_dashboard_states(event)

    assert states["binary_sensor.picot_replan_candidate"]["state"] == "off"
    assert states["sensor.picot_pv_deviation_status"]["state"] == "within_tolerance"
    assert states["sensor.picot_plan_review_status"]["state"] == "not_requested"
    assert states["sensor.picot_pv_energy_deviation_15m"]["state"] == "unknown"
