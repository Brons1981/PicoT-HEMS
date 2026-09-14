"""Audit regressions through persisted daily plans and the real HA dispatcher."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup, with_mode
from test_v2_canonical_execution_runtime import _live_run

from picot.v2.canonical_execution_runtime import (
    CanonicalDispatchOutcome,
    CanonicalExecutionRuntime,
    HomeAssistantCanonicalModeAdapter,
)


def daily_boundary(tmp_path, monkeypatch, *, discharge=False, charge=False):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    plan = store.load_active_daily_main_plan("battery")
    segment = (
        next(s for s in plan.segments if s.primitive.value == "balance_discharge_only")
        if discharge
        else plan.segments[0]
    )
    if charge:
        segment = next(s for s in plan.segments if s.primitive.value == "charge_at_power")
    source = replace(
        selected.planning_input,
        daily_charge_context=None,
        captured_at=segment.starts_at,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=segment.starts_at
        ),
    )
    source = with_mode(source, segment.primitive)
    return store, recover(source), segment


def test_persisted_daily_segment_constraints_reach_request(tmp_path, monkeypatch):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch)
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ok")
        ),
        commitment_store=store,
    )
    outcome = runtime.advance_committed_boundary(observed, execution_enabled=True)
    assert outcome.status == "dispatched"
    assert segment.soc_constraint is not None
    assert calls[0].segment_id == segment.segment_id
    assert calls[0].soc_constraint == segment.soc_constraint
    assert calls[0].energy_profile_id == segment.energy_profile_id


@pytest.mark.parametrize("soc", [0.01, 0.1])
def test_persisted_constraint_rejects_out_of_bounds_live_soc(tmp_path, monkeypatch, soc):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch, discharge=True)
    observed = replace(
        observed,
        current_storage_states=tuple(
            replace(state, current_soc=soc) for state in observed.current_storage_states
        ),
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda *args: calls.append(args) or CanonicalDispatchOutcome("dispatched", "bad"),
        commitment_store=store,
    )
    outcome = runtime.advance_committed_boundary(observed, execution_enabled=True)
    assert outcome.status == "blocked"
    assert outcome.failure_reason == "execution_soc_below_segment_minimum"
    assert calls == []


@pytest.mark.parametrize("failure", [TimeoutError("HA request timed out"), 503])
def test_real_dispatcher_failure_reaches_runtime(monkeypatch, failure):
    def send(self, call):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(
        "picot.v2.canonical_execution_runtime.HomeAssistantHttpTransport.send", send
    )
    run = _live_run()
    runtime = CanonicalExecutionRuntime(
        HomeAssistantCanonicalModeAdapter("test-token", lambda: run.planning_input.captured_at)
    )
    result = runtime.apply(run)
    assert result.vendor_result.status == "dispatch_failed"
    assert result.vendor_result.failure_reason
    assert runtime._pending_vendor_mode is None


def test_selector_feedback_has_bounded_wait_without_reassertion(tmp_path, monkeypatch):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch)
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda *args: calls.append(args) or CanonicalDispatchOutcome("dispatched", "ok"),
        commitment_store=store,
    )
    assert (
        runtime.advance_committed_boundary(observed, execution_enabled=True).status == "dispatched"
    )
    assert runtime.advance_committed_boundary(observed, execution_enabled=True).status == (
        "awaiting_mode_feedback"
    )
    at = observed.captured_at + timedelta(seconds=61)
    later = replace(
        observed,
        captured_at=at,
        daily_charge_context=replace(observed.daily_charge_context, restored_at=at),
        storage_mode_capability_evidence=replace(
            observed.storage_mode_capability_evidence, captured_at=at
        ),
        capability_snapshot_set=replace(observed.capability_snapshot_set, captured_at=at),
    )
    result = runtime.advance_committed_boundary(later, execution_enabled=True)
    assert result.status == "mode_feedback_timeout"
    assert result.failure_reason == "selector_mode_not_observed_before_timeout"
    assert len(calls) == 1
    assert runtime.advance_committed_boundary(later, execution_enabled=True).status == (
        "mode_feedback_timeout"
    )
    assert len(calls) == 1


def test_projected_request_preserves_optional_energy_profile_and_soc():
    from picot.domain.energy_path import SocConstraint

    run = _live_run()
    plan = run.execution_plan_set.plans[0]
    segment = replace(
        plan.segments[0],
        energy_profile_id="profile-approved",
        soc_constraint=SocConstraint(0.1, 0.95),
    )
    run = replace(
        run,
        execution_plan_set=replace(
            run.execution_plan_set, plans=(replace(plan, segments=(segment, *plan.segments[1:])),)
        ),
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ok")
        )
    )
    runtime.apply(run)
    assert calls[0].soc_constraint == segment.soc_constraint
    assert calls[0].energy_profile_id == "profile-approved"


def test_market_stop_reason_preserves_budget_decision(tmp_path, monkeypatch):
    from test_market_execution_guard import bound

    store, binding, start, observed = bound(tmp_path, monkeypatch)
    runtime = CanonicalExecutionRuntime(
        lambda *args: CanonicalDispatchOutcome("dispatched", "stop"), commitment_store=store
    )
    runtime.advance_committed_boundary(observed(start), execution_enabled=True)
    at = start + timedelta(seconds=binding.expected_export_wh * 3600 / 1200)
    result = runtime.advance_committed_boundary(observed(at), execution_enabled=True)
    assert result.reason == "market_export_budget_reached"
    assert result.failure_reason is None
    assert result.primitive.value == "balance_bidirectional"


def test_lower_soc_constraint_does_not_block_recovery_charge(tmp_path, monkeypatch):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch, charge=True)
    assert segment.primitive.value == "charge_at_power"
    observed = replace(
        observed,
        current_storage_states=tuple(
            replace(state, current_soc=0.01) for state in observed.current_storage_states
        ),
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ok")
        ),
        commitment_store=store,
    )
    result = runtime.advance_committed_boundary(observed, execution_enabled=True)
    assert result.status == "dispatched"
    assert calls[0].soc_constraint == segment.soc_constraint


def test_late_selector_observation_resolves_pending_without_another_command(tmp_path, monkeypatch):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch)
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda *args: calls.append(args) or CanonicalDispatchOutcome("dispatched", "ok"),
        commitment_store=store,
    )
    runtime.advance_committed_boundary(observed, execution_enabled=True)
    confirmed = replace(
        observed,
        storage_mode_capability_evidence=replace(
            observed.storage_mode_capability_evidence, current_vendor_mode="Test active"
        ),
    )
    result = runtime.advance_committed_boundary(confirmed, execution_enabled=True)
    assert result.status == "already_active"
    assert runtime._pending_vendor_mode is None
    assert len(calls) == 1


def test_full_battery_does_not_start_another_fast_charge(tmp_path, monkeypatch):
    store, observed, segment = daily_boundary(tmp_path, monkeypatch, charge=True)
    assert segment.primitive.value == "charge_at_power"
    observed = replace(
        observed,
        current_storage_states=tuple(
            replace(state, current_soc=1) for state in observed.current_storage_states
        ),
    )
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda *args: calls.append(args) or CanonicalDispatchOutcome("dispatched", "bad"),
        commitment_store=store,
    )
    result = runtime.advance_committed_boundary(observed, execution_enabled=True)
    assert result.status == "blocked"
    assert result.failure_reason == "execution_soc_above_segment_maximum"
    assert calls == []
