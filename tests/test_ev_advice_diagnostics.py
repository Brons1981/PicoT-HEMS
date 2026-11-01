import io
import json
import subprocess
import zipfile
from datetime import timedelta

import pytest
from test_ev_deadline_request import request
from test_ev_sessions import Rig

from picot_energy_devices.charging_advice import exchange_once
from picot_energy_devices.diagnostics import DiagnosticsRecorder
from picot_energy_devices.web_ui import DASHBOARD_HTML


def events(recorder):
    recorder.queue.join()
    with zipfile.ZipFile(io.BytesIO(recorder.export_zip())) as archive:
        return [json.loads(line) for line in archive.read("events.jsonl").splitlines()
                if json.loads(line)["kind"] == "ev_advice"]


def test_exchange_exports_request_returned_cost_comparison_and_acceptance(tmp_path):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    advice = {"contract": "energy-device-charging-advice:v1",
              "session_id": demand["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(), "status": "provisional",
              "total_cost_eur": 5.15, "baseline_total_cost_eur": 6.0, "savings_eur": 0.85,
              "provisional_reasons": ["prices_missing_before_deadline"],
              "candidate_comparisons": [{"candidate_id": "early", "total_cost_eur": 5.15,
                                          "private_token": "secret"}],
              "private_token": "secret"}

    class HA:
        def publish_catalog(self, entity, envelope):
            assert envelope["request"] == demand

        def state(self, entity):
            return {"attributes": advice}

    path = tmp_path / "diagnostics.sqlite3"
    recorder = DiagnosticsRecorder(path, options={})
    try:
        exchange_once(rig.manager, HA(), recorder)
        exchange_once(rig.manager, HA(), recorder)
        exported = events(recorder)
        assert len(exported) == 1
        data = exported[0]["data"]
        assert data["request"] == demand
        assert data["accepted"] is True
        assert data["advice"]["total_cost_eur"] == 5.15
        assert data["advice"]["candidate_comparisons"] == [
            {"candidate_id": "early", "total_cost_eur": 5.15}]
        assert "secret" not in json.dumps(exported)
        assert rig.commands == []
        advice["generated_at"] = (rig.now - timedelta(minutes=6)).isoformat()
        exchange_once(rig.manager, HA(), recorder)
        assert events(recorder)[-1]["data"]["accepted"] is False
    finally:
        recorder.close()
    restarted = DiagnosticsRecorder(path, options={})
    try:
        assert len(events(restarted)) == 2
    finally:
        restarted.close()


def explanation(advice):
    source = DASHBOARD_HTML.split("    function chargingAdviceExplanation(advice) {", 1)[1]
    source = "function chargingAdviceExplanation(advice) {" + source.split(
        "    function renderChargingAdvice(ev)", 1)[0]
    result = subprocess.run(
        ["node"], input=source + "\nconsole.log(JSON.stringify(chargingAdviceExplanation("
        + json.dumps(advice) + ")));", text=True, encoding="utf-8", capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_dashboard_explains_joint_costs_and_specific_provisional_reason():
    result = explanation({"status": "provisional", "total_cost_eur": 5.15,
                          "baseline_total_cost_eur": 6.0, "savings_eur": 0.85,
                          "provisional_reasons": ["prices_missing_before_deadline"]})
    assert "jouw eindtijd" in result["status"]
    assert "5,15" in result["cost"]
    assert "6,00" in result["cost"]
    assert "0,85" in result["cost"]
    assert "huis, auto en batterij" in result["cost"]


def test_dashboard_legacy_cost_is_not_mislabelled_as_joint_total():
    result = explanation({"status": "provisional", "estimated_incremental_cost_eur": 6.0})
    assert "niet meegeleverd" in result["status"]
    assert "zonder deze EV-sessie" in result["cost"]
    assert "totale kosten" not in result["cost"]


@pytest.mark.parametrize("joint_pending", [True, False])
def test_dashboard_waiting_is_only_for_joint_confirmation(joint_pending):
    source = DASHBOARD_HTML.split("    function chargingAdviceExplanation(advice) {", 1)[1]
    source = "function chargingAdviceExplanation(advice) {" + source.split(
        "    async function evChange(payload)", 1)[0]
    setup = """
const nodes={}; const el=id=>nodes[id]??={value:'',replaceChildren(){},append(){}};
const evBusy=false; const evChange=()=>{}; const number=String;
const document={createElement:()=>({})};
"""
    call = """
renderChargingAdvice({profile:{expected_power_w:2300,expected_duration_seconds:3600},
  charging_request:{state:'accepted',session_id:'one'},
  charging_advice:{status:'ready',generated_at:new Date().toISOString(),slots:[]},
  sessions:[{session_id:'one',state:'planned',start_status:'waiting_for_hems',
    accepted_advice:{},joint_pending:true,confirmed:false}]});
console.log(JSON.stringify(nodes));
"""
    call = call.replace("joint_pending:true", "joint_pending:" + json.dumps(joint_pending))
    result = subprocess.run(["node"], input=setup + source + call, text=True,
                            encoding="utf-8", capture_output=True, check=True)
    nodes = json.loads(result.stdout)
    assert ("Wachten op HEMS" in nodes["ev-advice-status"]["textContent"]) == joint_pending
    assert nodes["ev-advice-execute"]["disabled"] is True
    assert nodes["ev-advice-submit"]["disabled"] is True
    assert nodes["ev-advice-cancel"]["disabled"] is not joint_pending


@pytest.mark.parametrize("reason,expected", [
    ("joint_ev_selection_expired", "verlopen"),
    ("joint_ev_battery_owner_changed", "batterijplan is sinds het advies veranderd"),
    ("joint_ev_fresh_validation_failed:soc_goal_unreachable", "soc_goal_unreachable"),
])
def test_pending_joint_route_displays_specific_confirmation_failure(reason, expected):
    source = DASHBOARD_HTML.split("    function jointAcceptanceStatus(advice, session) {", 1)[1]
    source = "function jointAcceptanceStatus(advice, session) {" + source.split(
        "    function renderChargingAdvice(ev)", 1)[0]
    call = "\nconsole.log(JSON.stringify(jointAcceptanceStatus({}," + json.dumps(
        {"error": reason}) + ")));"
    result = subprocess.run(["node"], input=source + call, text=True, encoding="utf-8",
                            capture_output=True, check=True)
    text = json.loads(result.stdout)
    assert expected in text
    assert "De auto start niet" in text
