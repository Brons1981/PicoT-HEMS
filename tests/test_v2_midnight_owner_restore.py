"""A valid remaining route keeps its original owner across the calendar boundary."""

import json
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from test_daily_charge_runtime_input import snapshot
from test_daily_main_plan_recovery import selected_route  # noqa: F401
from test_market_plan_binding import proposal

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def test_uncompleted_previous_day_owner_survives_with_active_remaining_route(
    tmp_path, selected_route,  # noqa: F811
):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window, activate=True)
    now = assignment.ends_at + timedelta(minutes=40)
    assert plan.valid_until > now
    assert bound.completed_at is None
    before = path.read_bytes()

    source = replace(snapshot(now), horizon_end=plan.valid_until)
    restored = _restore_daily_charge_context(
        source, ActivePlanCommitmentStore(path), local_timezone=ZoneInfo(assignment.timezone)
    )

    context = restored.daily_charge_context
    assert context.status == "ready"
    assert context.reason is None
    assert context.assignments == (bound,)
    assert context.main_plans == (plan,)
    assert context.active_main_plan_ids == (plan.plan_id,)
    assert context.main_plans[0].snapshot_id == plan.snapshot_id
    assert context.assignments[0].completed_at is None
    assert path.read_bytes() == before


def test_unfinished_midnight_charge_keeps_following_route_without_extension(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import setup
    from test_daily_main_route_optimisation import fresh

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    base = recover()
    at = base.captured_at.replace(hour=23, minute=45)
    source = fresh(base, pv_factor=0, soc=0.95, tag="midnight-initial")
    source = replace(
        source, captured_at=at,
        current_storage_states=tuple(replace(s, measured_at=at)
                                     for s in source.current_storage_states),
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(replace(i, expected_energy_wh=0)
                            for i in source.household_load_forecast.intervals),
        ),
    )
    initial = pipeline.run(planning_input=recover(source))
    assert initial.execution_plan_set.plans, initial.evaluation.reason
    owner = store.load_daily_assignments()[0]
    plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    assert owner.main_segments[-1].ends_at == owner.ends_at
    assert plan.valid_until > owner.ends_at + timedelta(minutes=40)

    # Actual target missed: no later charge, invented completion or reset.
    now = owner.ends_at + timedelta(minutes=40)
    later = fresh(source, soc=0.97, tag="midnight-unfinished")
    later = replace(
        later, captured_at=now,
        current_storage_states=tuple(replace(s, measured_at=now)
                                     for s in later.current_storage_states),
        capability_snapshot_set=replace(later.capability_snapshot_set, captured_at=now),
    )
    before = store._path.read_bytes()
    restored = recover(later)
    assert restored.daily_charge_context.status == "ready"
    result = pipeline.run(planning_input=restored)
    assert result.evaluation.status == "plan_retained", result.evaluation.reason
    assert result.primitive_boundary.planned_primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert store.load_active_daily_main_plan(owner.execution_scope_id) == plan
    assert store.load_daily_assignments()[0] == owner
    assert owner.completed_at is None
    assert store._path.read_bytes() == before


def test_expired_plan_does_not_keep_uncompleted_previous_day_owner(
    tmp_path, selected_route,  # noqa: F811
):
    assignment, plan, window = selected_route
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(assignment)
    store.bind_daily_main_plan(plan=plan, window=window, activate=True)
    source = snapshot(plan.valid_until + timedelta(seconds=1))
    context = _restore_daily_charge_context(
        source, store, local_timezone=ZoneInfo(assignment.timezone)
    ).daily_charge_context
    assert context.status == "ready"
    assert context.assignments == ()
    assert context.main_plans == ()
    assert context.active_main_plan_ids == ()


def test_midnight_restore_does_not_accept_damaged_active_owner(tmp_path, selected_route):  # noqa: F811
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    store.bind_daily_main_plan(plan=plan, window=window, activate=True)
    payload = json.loads(path.read_text())
    payload["active_daily_main_assignments"][assignment.execution_scope_id] = "wrong-owner"
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    context = _restore_daily_charge_context(
        snapshot(assignment.ends_at + timedelta(minutes=40)),
        ActivePlanCommitmentStore(path),
        local_timezone=ZoneInfo(assignment.timezone),
    ).daily_charge_context
    assert context.status == "blocked"
    assert context.reason == "active daily main plan scope or binding invalid"
    assert path.read_bytes() == before


def test_shared_market_plan_keeps_previous_day_charge_lineage(tmp_path, selected_route):  # noqa: F811
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window, activate=True)
    shared = proposal(store, plan)
    store.bind_market_plan(**shared)
    now = assignment.ends_at + timedelta(minutes=40)
    assert shared["plan"].valid_until > now
    before = path.read_bytes()

    context = _restore_daily_charge_context(
        snapshot(now), ActivePlanCommitmentStore(path), local_timezone=ZoneInfo(assignment.timezone)
    ).daily_charge_context

    assert context.status == "ready", context.reason
    assert context.assignments == (bound,)
    assert context.active_main_plan_ids == (shared["plan"].plan_id,)
    assert set(p.plan_id for p in context.main_plans) == {plan.plan_id, shared["plan"].plan_id}
    assert context.market_plan_bindings == (shared["binding"],)
    assert path.read_bytes() == before


def test_shared_owner_with_damaged_origin_is_not_reconstructed(tmp_path, selected_route):  # noqa: F811
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    store.bind_daily_main_plan(plan=plan, window=window, activate=True)
    shared = proposal(store, plan)
    store.bind_market_plan(**shared)
    payload = json.loads(path.read_text())
    stored = payload["execution_plans"][shared["plan"].plan_id]
    segment = next(s for s in stored["segments"] if s["main_assignment_id"] is not None)
    segment["retained_execution_origin"]["segment_id"] = "unrelated-segment"
    path.write_text(json.dumps(payload))
    before = path.read_bytes()

    context = _restore_daily_charge_context(
        snapshot(assignment.ends_at + timedelta(minutes=40)), ActivePlanCommitmentStore(path),
        local_timezone=ZoneInfo(assignment.timezone),
    ).daily_charge_context

    assert context.status == "blocked"
    assert context.reason == "shared main segment must retain original completion lineage"
    assert path.read_bytes() == before
