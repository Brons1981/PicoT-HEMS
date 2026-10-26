"""Completion during HA downtime must not strand remaining execution."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_active_pipeline import setup

from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def completed_case(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    main = owner.main_segments[0]
    at = main.starts_at + timedelta(seconds=30)
    store.recover_historical_main_completion(
        assignment_id=owner.assignment_id,
        measured_at=at - timedelta(seconds=10),
        observed_at=at,
        soc=1,
        evidence_id="ha-soc-history:outage-full",
    )
    source = replace(
        selected.planning_input,
        captured_at=at,
        daily_charge_context=None,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=at
        ),
        current_storage_states=tuple(
            replace(s, current_soc=1, measured_at=at)
            for s in selected.planning_input.current_storage_states
        ),
    )
    return store, pipeline, recover, source


@pytest.mark.parametrize("reset", [False, True])
def test_completed_day_gets_executable_remainder_without_next_day(tmp_path, monkeypatch, reset):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    completed = store.load_daily_assignments()
    if reset:
        store.request_planning_recovery(
            request_id="after-ha-update", requested_at=source.captured_at
        )
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    assert plan is not None
    assert not any(
        s.main_assignment_id == completed[0].assignment_id and s.ends_at > source.captured_at
        for s in plan.segments
    )
    assert store.load_daily_assignments() == completed
    assert result.evaluation.canonical_record is not None
    assert result.candidate_set.candidates and result.outcomes.canonical_outcomes
    if reset:
        assert store.daily_recalculation_status()["status"] == "completed"
    restarted = ActivePlanCommitmentStore(store._path)
    restored = _restore_daily_charge_context(source, restarted, local_timezone=ZoneInfo("UTC"))
    assert restored.daily_charge_context.status == "ready", restored.daily_charge_context.reason
    assert plan.plan_id in restored.daily_charge_context.active_main_plan_ids
    again = pipeline.run(planning_input=recover(source))
    assert again.evaluation.status == "plan_retained"
    assert store.load_active_daily_main_plan("battery") == plan


def test_completed_recovery_waits_for_prices_and_retries(tmp_path, monkeypatch):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    store.request_planning_recovery(request_id="retry", requested_at=source.captured_at)
    failed = pipeline.run(planning_input=recover(replace(source, price_points=())))
    assert failed.evaluation.status == "fallback_active"
    assert store.load_active_daily_main_plan("battery") is None
    assert store.daily_recalculation_status()["status"] == "pending"
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason


def test_completed_recovery_does_not_reopen_goal_after_soc_has_fallen(tmp_path, monkeypatch):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    completed = store.load_daily_assignments()
    original = store.load_active_daily_main_plan("battery")
    source = replace(
        source,
        current_storage_states=tuple(
            replace(state, current_soc=0.95) for state in source.current_storage_states
        ),
    )
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert store.load_daily_assignments() == completed
    plan = store.load_active_daily_main_plan("battery")
    for part in plan.segments:
        old = next(
            s
            for s in original.segments
            if s.starts_at <= part.starts_at < part.ends_at <= s.ends_at
        )
        if old.main_assignment_id != completed[0].assignment_id:
            for field in (
                "primitive",
                "requested_power_w",
                "soc_constraint",
                "purpose",
                "charge_source_policy",
                "main_assignment_id",
            ):
                assert getattr(part, field) == getattr(old, field)
        else:
            assert part.primitive.value in {"balance_bidirectional", "balance_discharge_only"}
            assert part.main_assignment_id is None


def test_failed_persistence_retains_old_plan_and_retries(tmp_path, monkeypatch):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    old = store.load_active_daily_main_plan("battery")
    before = store._path.read_bytes()
    write = store._write

    def unavailable(payload):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "_write", unavailable)
    failed = pipeline.run(planning_input=recover(source))
    assert failed.evaluation.status == "fallback_active"
    assert "disk unavailable" in failed.evaluation.reason
    assert store._path.read_bytes() == before
    assert store.load_active_daily_main_plan("battery") == old
    monkeypatch.setattr(store, "_write", write)
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason


def test_completed_recovery_can_repeat_after_another_reset(tmp_path, monkeypatch):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    for n in range(2):
        at = source.captured_at + timedelta(seconds=n)
        store.request_planning_recovery(request_id=f"reset-{n}", requested_at=at)
        result = pipeline.run(planning_input=recover(source))
        assert result.evaluation.status == "winner_selected", result.evaluation.reason
        assert store.daily_recalculation_status()["status"] == "completed"
        assert store.load_active_daily_main_plan("battery") is not None


@pytest.mark.parametrize("corruption", ["missing", "completion", "instruction"])
def test_corrupted_completed_binding_blocks_restore(tmp_path, monkeypatch, corruption):
    import json

    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected"
    payload = json.loads(store._path.read_text())
    pid = payload["active_execution_plan_ids"]["battery"]
    if corruption == "missing":
        del payload["completed_route_bindings"][pid]["assignment_id"]
    elif corruption == "completion":
        payload["completed_route_bindings"][pid]["completion_evidence_id"] = "invented"
    else:
        payload["execution_plans"][pid]["segments"][0]["main_assignment_id"] = "reopened"
    store._path.write_text(json.dumps(payload))
    restarted = ActivePlanCommitmentStore(store._path)
    with pytest.raises(ValueError):
        restarted.load_active_daily_main_plan("battery")
    restored = _restore_daily_charge_context(source, restarted, local_timezone=ZoneInfo("UTC"))
    assert restored.daily_charge_context.status == "blocked"


@pytest.mark.parametrize("reset", [False, True])
def test_repaired_plan_passes_actual_execution_boundary(tmp_path, monkeypatch, reset):
    from test_daily_main_active_pipeline import with_mode

    from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime

    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    if reset:
        store.request_planning_recovery(request_id="execution", requested_at=source.captured_at)
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected"
    plan = store.load_active_daily_main_plan("battery")
    source = with_mode(source, plan.segments[0].primitive, current_mode="Test active")

    def no_dispatch(*args):
        raise AssertionError("confirmed mode must not be sent again")

    runtime = CanonicalExecutionRuntime(no_dispatch, commitment_store=store)
    runtime.apply(result)  # Admit the freshly recovered plan before its clock boundary.
    boundary = runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert boundary.status == "already_active", boundary


    manual = replace(source, storage_mode_control_provenance=replace(
        source.storage_mode_control_provenance, status="manual_override",
        manual_override_active=True, transition_reason="manual change"))
    blocked = runtime.advance_committed_boundary(recover(manual), execution_enabled=True)
    assert blocked.status == "blocked"
    assert blocked.failure_reason == "manual_override_active"


@pytest.mark.parametrize("field,value", [("capability_snapshot_set", None),
                                        ("storage_physical_limits", ())])
def test_completed_recovery_requires_physical_evidence(tmp_path, monkeypatch, field, value):
    store, pipeline, recover, source = completed_case(tmp_path, monkeypatch)
    store.request_planning_recovery(request_id="physical", requested_at=source.captured_at)
    result = pipeline.run(planning_input=recover(replace(source, **{field: value})))
    assert result.evaluation.status == "fallback_active"
    assert store.load_active_daily_main_plan("battery") is None
    assert store.daily_recalculation_status()["status"] == "pending"
