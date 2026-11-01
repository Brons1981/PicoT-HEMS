"""A bridge between two main blocks must not replay the elapsed first block."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_bridge_pipeline import started
from test_daily_main_route_optimisation import fresh

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.daily_charge_assignment import DailyChargeSegment
from picot.v2.plan_commitment_store import (
    ActivePlanCommitmentStore,
    _serialize_daily,
    _serialize_execution_plan,
)


def between_blocks(tmp_path, monkeypatch, offset_seconds=0):
    store, pipeline, recover, source, completed, _ = started(tmp_path, monkeypatch)
    owner = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    first = plan.segments[0]
    end = source.captured_at + timedelta(minutes=5)
    assert first.main_assignment_id is None and first.ends_at > end
    solar = replace(first, segment_id="elapsed-solar", ends_at=end,
                    primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                    charge_source_policy=ChargeSourcePolicy.PV_ONLY,
                    main_assignment_id=owner.assignment_id,
                    purpose="main-charge:" + owner.assignment_id)
    segments = (solar, replace(first, starts_at=end), *plan.segments[1:])
    plan = replace(plan, segments=tuple(replace(s, order=n + 1)
                                       for n, s in enumerate(segments)))
    owner = replace(owner, main_segments=(
        DailyChargeSegment(solar.segment_id, solar.starts_at, solar.ends_at),
        *owner.main_segments))
    # Persist the already-owned split route as the incident's starting state.
    payload = store._load_payload()
    payload["daily_assignments"][owner.assignment_id] = _serialize_daily(owner)
    payload["daily_execution_plans"][owner.assignment_id] = _serialize_execution_plan(plan)
    payload["execution_plans"][plan.plan_id] = _serialize_execution_plan(plan)
    store._write(payload)
    at = end + timedelta(seconds=offset_seconds)
    observation = fresh(source, soc=0.1, tag="between-main-blocks")
    observation = replace(observation, captured_at=at,
        current_storage_states=tuple(replace(s, measured_at=at)
                                     for s in observation.current_storage_states),
        capability_snapshot_set=replace(observation.capability_snapshot_set, captured_at=at))
    return store, pipeline, recover(observation), owner, plan, completed


@pytest.mark.parametrize("offset_seconds", [0, 52])
def test_bridge_after_elapsed_solar_preserves_future_main_and_history(
    tmp_path, monkeypatch, offset_seconds,
):
    store, pipeline, snapshot, owner, original, completed = between_blocks(
        tmp_path, monkeypatch, offset_seconds)
    result = pipeline.run(planning_input=snapshot)
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert result.evaluation.daily_bridge.status == "energy_shortfall"
    replacement = store.load_active_daily_main_plan(owner.execution_scope_id)
    remaining = [s for s in original.segments if s.main_assignment_id == owner.assignment_id
                 and s.ends_at > snapshot.captured_at]
    actual = [s for s in replacement.segments if s.main_assignment_id == owner.assignment_id]
    fields = ("starts_at", "ends_at", "primitive", "requested_power_w", "soc_constraint",
              "capability_id", "charge_source_policy", "energy_profile_id")
    assert len(remaining) == len(actual) == 1
    assert [tuple(getattr(s, f) for f in fields) for s in actual] == [
        tuple(getattr(s, f) for f in fields) for s in remaining]
    restarted = ActivePlanCommitmentStore(store._path)
    history = restarted._load_payload()["daily_main_history"][original.plan_id]
    assert history["assignment"] == _serialize_daily(owner)
    assert history["plan"] == _serialize_execution_plan(original)
    assert restarted.load_active_daily_main_plan(owner.execution_scope_id) == replacement
    assert completed in restarted.load_daily_assignments()
    assert next(a for a in restarted.load_daily_assignments()
                if a.assignment_id == owner.assignment_id).completed_at is None


@pytest.mark.parametrize("change", [
    {"requested_power_w": 1000.0},
    {"charge_source_policy": ChargeSourcePolicy.PV_ONLY},
])
def test_future_main_changes_still_rejected_atomically(tmp_path, monkeypatch, change):
    store, pipeline, snapshot, owner, original, _ = between_blocks(tmp_path, monkeypatch, 52)
    before = store._path.read_bytes()
    bind = store.bind_daily_main_plan

    def tampered(**kwargs):
        plan = kwargs["plan"]
        kwargs["plan"] = replace(plan, segments=tuple(
            replace(s, **change) if s.main_assignment_id == owner.assignment_id else s
            for s in plan.segments))
        return bind(**kwargs)

    monkeypatch.setattr(store, "bind_daily_main_plan", tampered)
    result = pipeline.run(planning_input=snapshot)
    assert result.evaluation.status == "fallback_active"
    assert result.evaluation.reason == "bridge cannot move or change the next main session"
    assert store._path.read_bytes() == before
    assert store.load_active_daily_main_plan(owner.execution_scope_id) == original
