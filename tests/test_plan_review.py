from picot.addon.plan_review import evaluate_plan_review, plan_review_log_event


def test_no_candidate_does_not_open_review() -> None:
    result = evaluate_plan_review({"pv_deviation_replan_candidate": False})

    assert result["plan_review_status"] == "not_requested"
    assert result["plan_review_outcome"] is None
    assert result["plan_review_action"] == "keep_current_plan"
    assert result["plan_review_control_change_allowed"] is False


def test_candidate_opens_review_but_keeps_current_plan() -> None:
    result = evaluate_plan_review(
        {
            "pv_deviation_replan_candidate": True,
            "pv_deviation_evaluator_status": "persistent_under_forecast",
            "pv_rolling_deviation_percent": -42.2,
            "grid_import_w": 1.9,
            "grid_export_w": 0.0,
            "zendure_soc_percent": 92.0,
            "zendure_charge_power_w": 1200.0,
            "zendure_discharge_power_w": 0.0,
        }
    )

    assert result["plan_review_status"] == "completed"
    assert result["plan_review_outcome"] == "current_plan_still_feasible"
    assert result["plan_review_action"] == "keep_current_plan"
    assert result["plan_review_feasibility_scope"] == "phase1_observation_only"
    assert result["plan_review_control_change_allowed"] is False
    assert result["plan_review_grid_import_w"] == 1.9
    assert result["plan_review_battery_soc_percent"] == 92.0


def test_review_log_preserves_no_action_evidence() -> None:
    event = {
        "telemetry_updated_at": "2026-08-10T13:30:00+02:00",
        **evaluate_plan_review(
            {
                "pv_deviation_replan_candidate": True,
                "pv_deviation_evaluator_status": "persistent_under_forecast",
                "pv_rolling_deviation_percent": -35.0,
                "grid_import_w": 25.0,
                "grid_export_w": 0.0,
                "zendure_soc_percent": 90.0,
                "zendure_charge_power_w": 900.0,
                "zendure_discharge_power_w": 0.0,
            }
        ),
    }

    log = plan_review_log_event(event)

    assert log["event"] == "picot_plan_review"
    assert log["outcome"] == "current_plan_still_feasible"
    assert log["action"] == "keep_current_plan"
    assert log["control_change_allowed"] is False
    assert log["grid_import_w"] == 25.0
