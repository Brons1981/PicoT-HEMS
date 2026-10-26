from test_dashboard_attention import run
from test_hems_health_alerts import Recorder

from picot.v2.health_alerts import observe_execution
from picot.v2.recovery_messages import recovery_details, recovery_message
from picot.v2.web_ui import pipeline_result_nl


def test_completion_wait_explains_cause_effect_and_automatic_action():
    code = "historical_main_completed_waiting_for_reconciliation"
    message = pipeline_result_nl(stage=7, state="blocked", attributes={"blockers": [code]})
    for required in ("100% SOC", "oude laadblok", "automatisch", "niet nodig", code):
        assert required in message
    faults = run(
        ["dashboardFaults"],
        "dashboardFaults({pipeline:[{stage:7,health:'fault',"
        "fault_explanation_nl:'Het oude laadblok wordt automatisch hersteld.',"
        "attributes:{blockers:['historical_main_completed_waiting_for_reconciliation']}}]})",
    )
    assert faults == ["Het oude laadblok wordt automatisch hersteld."]


def test_known_cause_does_not_hide_additional_unknown_blocker():
    message = recovery_details(
        {"blockers": ["daily_main_planning_data_unavailable", "sensor.battery_soc unavailable"]}
    )
    assert "sensor.battery_soc unavailable" in message
    assert "automatisch" in message
    assert recovery_details({"error": "unknown"}) is None


def test_fallback_does_not_claim_nom_confirmation_and_failure_retains_detail():
    assert "terugmelding" in recovery_message("daily_main_active_plan_unavailable")
    recorder = Recorder()
    observe_execution(
        recorder,
        status="failed",
        reason=None,
        failure_reason="completed_day_recovery_failed:disk unavailable",
    )
    message = recorder.events[-1][2]
    assert "disk unavailable" in message
    assert "volgende regelcyclus" in message


def test_missing_input_names_are_exact():
    message = recovery_message(
        "daily_main_planning_data_unavailable:price_points,current_storage_states"
    )
    assert "elektriciteitsprijzen" in message
    assert "actuele batterijstatus" in message
    assert "zonneproductie" not in message
