"""A completed actuator result follows newer observations made during planning."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from test_daily_main_active_pipeline import setup, with_mode

import picot.v2.live_runtime as live
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.runtime.runtime_monitor import RuntimeMonitorSession
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.storage_mode_transition_history import StorageModeTransitionHistoryStore
from picot.v2.web_ui import WebViewStore


@pytest.mark.parametrize("dispatch_status", ["dispatched", "dispatch_failed"])
@pytest.mark.parametrize("monitor_failure", [False, True])
def test_fallback_after_newer_observation_preserves_dispatch_ownership(
    tmp_path, monkeypatch, dispatch_status, monitor_failure,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    original_plan = store.load_active_daily_main_plan("battery")
    source = with_mode(recover(), ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                       current_mode="Snel opladen")
    source = replace(source, pv_energy_timeline=None)
    newer = source.captured_at + timedelta(seconds=60)
    completed = newer + timedelta(seconds=30)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return completed

    monkeypatch.setattr(live, "datetime", Clock)
    monkeypatch.setattr(live.HomeAssistantProjectionSink, "publish", lambda *args: None)
    monitor = RuntimeMonitorSession()
    live._observe_execution_status(
        monitor, status="already_active", source_reference="committed-boundary",
        observed_at=newer, observation_id="newer-boundary",
    )
    if monitor_failure:
        def fail(*args, **kwargs):
            raise ValueError("injected monitor failure")
        monkeypatch.setattr(monitor, "observe", fail)

    provenance_store = StorageModeProvenanceStore(tmp_path / "provenance.json")
    provenance = LiveStorageModeProvenanceRuntime(provenance_store)
    provenance.observe_vendor_mode("Snel opladen", observed_at=source.captured_at)
    provenance.record_planner_application(
        "Snel opladen", applied_at=source.captured_at, application_id="prior-charge",
    )
    switches = StorageModeTransitionHistoryStore(tmp_path / "switches.jsonl")
    dispatched = []

    def dispatch(request, mapping):
        dispatched.append((request, mapping))
        return CanonicalDispatchOutcome(dispatch_status, "fallback-command")

    def execute():
        return live._execute_planning_bundle(
            token="unused", canonical_pipeline=pipeline,
            price_config=PriceOpportunityConfig(0.02, 0.02, "test"),
            bundle=PlanningInputBundle(source, (), (), source.captured_at, source.captured_at),
            web_view_store=WebViewStore(), execution_enabled=True,
            canonical_execution_runtime=CanonicalExecutionRuntime(dispatch, commitment_store=store),
            storage_mode_provenance_runtime=provenance,
            storage_mode_transition_history=switches, runtime_monitor=monitor,
        )

    if monitor_failure:
        with pytest.raises(ValueError, match="injected monitor failure"):
            execute()
    else:
        execute()
        assert monitor.state.last_processed_observation_at == completed
        if dispatch_status == "dispatch_failed":
            assert monitor.state.replan_required

    assert len(dispatched) == 1
    request, mapping = dispatched[0]
    assert request.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert request.requested_at == source.captured_at
    assert store.load_active_daily_main_plan("battery") == original_plan
    restarted = LiveStorageModeProvenanceRuntime(provenance_store)
    if dispatch_status == "dispatched":
        assert provenance_store.load().last_planner_vendor_mode == mapping.fixed_value
        assert len(switches.load()) == 1
        observed = restarted.observe_vendor_mode(mapping.fixed_value, observed_at=completed)
        assert not observed.manual_override_active
        assert observed.status == "planner_owned"
        manual = restarted.observe_vendor_mode(
            "Standby", observed_at=completed + timedelta(seconds=1),
        )
        assert manual.manual_override_active
    else:
        assert provenance_store.load().last_planner_vendor_mode == "Snel opladen"
        assert not switches.load()
