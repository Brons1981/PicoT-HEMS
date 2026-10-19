"""Explicit retirement is durable and distinct from measured completion."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_supplemental_charge_commitment import charged

from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


@pytest.fixture
def retirement(tmp_path, monkeypatch):
    store, _, _, _, _ = charged(tmp_path, monkeypatch)
    goals = store.load_supplemental_assignments()
    goal = goals[0]
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    plan = replace(
        plan,
        plan_id="replacement-without-bridge",
        created_at=goal.starts_at - timedelta(seconds=1),
        segments=tuple(
            replace(s, purpose="self_consumption") if s.purpose == goal.assignment_id else s
            for s in plan.segments
        ),
    )
    window = SimpleNamespace(
        supplemental_assignments=tuple(g for g in goals if g != goal),
        supplemental_retirements=(goal.assignment_id,),
    )
    return store, goal, plan, window


def test_retirement_survives_restart_without_faking_completion(retirement):
    store, goal, plan, window = retirement
    payload = store._load_payload()
    market_before = payload.get("market_plan_bindings")
    store._bind_supplemental(payload, plan, window)
    store._write(payload)
    restarted = ActivePlanCommitmentStore(store._path)
    assert goal.assignment_id not in {
        g.assignment_id for g in restarted.load_supplemental_assignments()
    }
    persisted = json.loads(store._path.read_text())
    record = persisted["supplemental_retirements"][goal.assignment_id]
    assert record["assignment"]["completed_at"] is None
    assert record["assignment"]["completion_evidence_id"] is None
    assert record["reason"] == "bridge_need_no_longer_present"
    assert record["replacement_plan_id"] == plan.plan_id
    assert record["retired_at"] == plan.created_at.isoformat()
    assert persisted["supplemental_history"][goal.assignment_id][-1] == record["assignment"]
    assert persisted.get("market_plan_bindings") == market_before


@pytest.mark.parametrize("invalid", ["unlisted", "unknown", "started", "completed", "retained"])
def test_invalid_retirement_cannot_change_persisted_state(retirement, invalid):
    store, goal, plan, window = retirement
    if invalid == "unlisted":
        window.supplemental_retirements = ()
    elif invalid == "unknown":
        window.supplemental_retirements = ("unknown-goal",)
    elif invalid == "started":
        plan = replace(plan, created_at=goal.starts_at)
    elif invalid == "completed":
        payload = store._load_payload()
        payload["supplemental_assignments"][goal.assignment_id] = store._supplemental_record(
            replace(goal, completed_at=goal.ends_at, completion_evidence_id="measured")
        )
        store._write(payload)
    elif invalid == "retained":
        window.supplemental_assignments += (goal,)
    before = store._path.read_bytes()
    with pytest.raises(ValueError):
        store._bind_supplemental(store._load_payload(), plan, window)
    assert store._path.read_bytes() == before


def test_retirement_cannot_leave_owned_execution_or_reopen(retirement):
    store, goal, plan, window = retirement
    original = store.load_active_daily_main_plan(goal.execution_scope_id)
    with pytest.raises(ValueError, match="execution cannot remain"):
        store._bind_supplemental(
            store._load_payload(), replace(plan, segments=original.segments), window
        )
    payload = store._load_payload()
    store._bind_supplemental(payload, plan, window)
    store._write(payload)
    window.supplemental_retirements = ()
    window.supplemental_assignments += (goal,)
    with pytest.raises(ValueError, match="cannot be reopened"):
        store._bind_supplemental(store._load_payload(), plan, window)
