"""The final execution decision retains its own complete fresh input."""
import json
from dataclasses import replace
from datetime import timedelta

from test_daily_main_active_pipeline import setup

from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.live_runtime import _execute_planning_bundle
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.planning_incident_history import PlanningIncidentHistory
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.web_ui import WebViewStore


def test_final_execution_input_is_persisted_separately_from_planning(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    planned = recover()
    bundle = PlanningInputBundle(planned, (), (), planned.captured_at, planned.captured_at)
    fresh_inputs = []

    def refresh():
        now = planned.captured_at + timedelta(seconds=1)
        fresh = recover(replace(
            planned, daily_charge_context=None, captured_at=now,
            snapshot_id="snapshot-final-execution",
            pv_energy_timeline=replace(planned.pv_energy_timeline,
                                       snapshot_id="snapshot-final-execution"),
            household_load_forecast=replace(planned.household_load_forecast,
                                             snapshot_id="snapshot-final-execution"),
            capability_snapshot_set=replace(planned.capability_snapshot_set, captured_at=now,
                                             snapshot_id="snapshot-final-execution"),
        ))
        fresh_inputs.append(fresh)
        return fresh

    monkeypatch.setattr("picot.v2.live_runtime.HomeAssistantProjectionSink.publish",
                        lambda *args: None)
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    _execute_planning_bundle(
        token="test-token", canonical_pipeline=pipeline,
        price_config=PriceOpportunityConfig(0.02, 0.02, "test"),
        bundle=bundle, web_view_store=WebViewStore(),
        canonical_execution_runtime=CanonicalExecutionRuntime(
            lambda *args: CanonicalDispatchOutcome("dispatched", "command-test"),
            commitment_store=store,
        ),
        execution_enabled=True, refresh_execution_input=refresh,
        planning_incident_history=history,
    )
    assert len(fresh_inputs) == 1
    poll = json.loads(history.path.read_text().splitlines()[0])["poll"]
    assert poll["planning_input"]["snapshot_id"] == planned.snapshot_id
    executed = poll["runtime_diagnostics"]["execution_observation"]["planning_input"]
    assert executed["snapshot_id"] == "snapshot-final-execution"
    assert executed["daily_charge_context"]["active_main_plan_ids"]
    assert executed["capability_snapshot_set"]
    assert executed["storage_physical_limits"]
