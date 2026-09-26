"""The final execution decision retains its own complete fresh input."""
import json
from dataclasses import replace
from datetime import timedelta

from test_daily_main_active_pipeline import setup, with_mode
from test_daily_main_route_optimisation import fresh

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.live_runtime import _execute_planning_bundle
from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.planning_incident_history import PlanningIncidentHistory
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.storage_mode_transition_history import StorageModeTransitionHistoryStore
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


def test_switch_after_planning_uses_fresh_execution_reason(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    initial = with_mode(
        recover(fresh(recover(), pv_factor=0, soc=0.7)),
        ExecutionPrimitive.CHARGE_AT_POWER, current_mode="Snel opladen",
    )
    pipeline.run(planning_input=initial, control_change_allowed=True)
    plan = store.load_active_daily_main_plan("battery")
    grid = next(s for s in plan.segments if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    following = next(s for s in plan.segments if s.starts_at == grid.ends_at)
    planned = recover(initial)
    bundle = PlanningInputBundle(planned, (), (), planned.captured_at, planned.captured_at)

    def refresh():
        at = grid.ends_at + timedelta(seconds=1)
        observed = fresh(replace(planned, storage_mode_capability_evidence=None),
                         tag="after-grid-boundary")
        observed = replace(
            observed, captured_at=at,
            current_storage_states=tuple(
                replace(s, measured_at=at) for s in observed.current_storage_states
            ),
            capability_snapshot_set=replace(observed.capability_snapshot_set, captured_at=at),
        )
        return with_mode(recover(observed), following.primitive, current_mode="Snel opladen")

    monkeypatch.setattr("picot.v2.live_runtime.HomeAssistantProjectionSink.publish",
                        lambda *args: None)
    provenance = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(tmp_path / "provenance.json")
    )
    provenance.observe_vendor_mode("Snel opladen", observed_at=planned.captured_at)
    history = StorageModeTransitionHistoryStore(tmp_path / "switches.jsonl")
    incidents = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    dispatched = []

    def dispatch(request, mapping):
        dispatched.append(request)
        return CanonicalDispatchOutcome("dispatched", "command-after-grid")

    _execute_planning_bundle(
        token="test-token", canonical_pipeline=pipeline,
        price_config=PriceOpportunityConfig(0.02, 0.02, "test"),
        bundle=bundle, web_view_store=WebViewStore(),
        canonical_execution_runtime=CanonicalExecutionRuntime(dispatch, commitment_store=store),
        execution_enabled=True, refresh_execution_input=refresh,
        storage_mode_provenance_runtime=provenance, storage_mode_transition_history=history,
        planning_incident_history=incidents,
    )
    event, = history.load()
    assert event.reason == "active canonical MEP segment boundary"
    assert event.occurred_at == grid.ends_at + timedelta(seconds=1)
    assert event.plan_id == plan.plan_id
    assert dispatched[0].primitive is following.primitive
    poll = json.loads(incidents.path.read_text().splitlines()[0])["poll"]
    assert poll["evaluation"]["reason"] == "daily_main_route_retained_without_optimisation_trigger"
    assert poll["primitive_boundary"]["execution_reason"] == event.reason
    assert store.load_active_daily_main_plan("battery") == plan
