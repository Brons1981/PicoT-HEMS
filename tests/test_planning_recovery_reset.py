"""Explicit recovery releases old plans without inventing observed completion."""
from dataclasses import replace
from datetime import timedelta
from threading import Event
from zoneinfo import ZoneInfo

from test_daily_main_active_pipeline import setup

from picot.v2.live_runtime import (
    PlanningResetBarrier,
    _request_daily_recalculation_and_replan,
    _restore_daily_charge_context,
)
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.web_ui import WebViewStore


def test_late_restored_day_does_not_block_tomorrow_after_explicit_reset(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    initial = recover()
    initial = replace(initial, horizon_end=initial.captured_at + timedelta(hours=48),
        price_points=tuple(replace(p, ends_at=initial.captured_at + timedelta(hours=48))
                           for p in initial.price_points),
        household_load_forecast=replace(initial.household_load_forecast, intervals=tuple(
            replace(initial.household_load_forecast.intervals[0],
                    interval_id=f"load-{i}",
                    starts_at=initial.captured_at + timedelta(minutes=15*i),
                    ends_at=initial.captured_at + timedelta(minutes=15*(i+1)))
            for i in range(192))),
        pv_energy_timeline=replace(initial.pv_energy_timeline, intervals=tuple(
            replace(initial.pv_energy_timeline.intervals[0], interval_id=f"pv-{i}",
                    starts_at=initial.captured_at + timedelta(minutes=30*i),
                    ends_at=initial.captured_at + timedelta(minutes=30*(i+1)))
            for i in range(96))))
    first = pipeline.run(planning_input=recover(initial))
    source = first.planning_input
    at = source.captured_at.replace(hour=23, minute=45)
    source = replace(source, captured_at=at, daily_charge_context=None,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        current_storage_states=tuple(
        replace(s, current_soc=.48, measured_at=at) for s in source.current_storage_states),
        pv_energy_timeline=replace(source.pv_energy_timeline, intervals=tuple(
            replace(i, pv_energy_wh=0, forecast_lower_energy_wh=0,
                    forecast_central_energy_wh=0, forecast_upper_energy_wh=0)
            for i in source.pv_energy_timeline.intervals)))
    failed = pipeline.run(planning_input=recover(source))
    assert failed.evaluation.status == 'fallback_active'
    assert failed.evaluation.reason == 'insufficient_remaining_charge_capacity'
    before = store._path.read_bytes()
    event = Event()
    result = _request_daily_recalculation_and_replan(
        store=store, barrier=PlanningResetBarrier(), replan_requested=event,
        web_view_store=WebViewStore(), request_id='restore-recovery', requested_at=at,
        recovery_reset=True,
    )
    assert result['status'] == 'pending' and event.is_set()
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == 'winner_selected', result.evaluation.reason
    owner = next(a for a in store.load_daily_assignments() if a.delivery_date == at.date())
    assert owner.completed_at is None
    assert owner.assignment_id in store.deferred_recovery_assignment_ids()
    plan = store.load_active_daily_main_plan('battery')
    assert plan is not None
    assert store.daily_recalculation_status()['status'] == 'completed'
    history = store._load_payload()['planning_recovery_history']['restore-recovery']
    import json
    assert history['previous_state'] == json.loads(before)
    restarted = ActivePlanCommitmentStore(store._path)
    restored = _restore_daily_charge_context(source, restarted, local_timezone=ZoneInfo('UTC'))
    assert owner.assignment_id not in {
        a.assignment_id for a in restored.daily_charge_context.assignments
    }
    tomorrow = at.date() + timedelta(days=1)
    assert next(a for a in restarted.load_daily_assignments()
                if a.delivery_date == tomorrow).route_plan_id == plan.plan_id


def test_reset_without_existing_plan_still_requests_fresh_planning(tmp_path):
    store = ActivePlanCommitmentStore(tmp_path / 'plans.json')
    from datetime import UTC, datetime
    at = datetime(2026, 10, 8, 23, 45, tzinfo=UTC)
    result = store.request_planning_recovery(request_id='empty', requested_at=at)
    assert result['status'] == 'pending'
    assert store.load_daily_recalculation_request() is None
    saved = store._path.read_bytes()
    store.request_planning_recovery(request_id='empty', requested_at=at)
    assert store._path.read_bytes() == saved


def test_recovery_preserves_completed_goal_and_archives_market_obligations(tmp_path):
    from test_market_revision_comparison import scenario
    store, source, _ = scenario(tmp_path, soc=1.0)
    owners = store.load_daily_assignments()
    completed = tuple(a for a in owners if a.completed_at is not None)
    assert completed
    before = store._load_payload()
    store.request_planning_recovery(request_id='market-reset', requested_at=source.captured_at)
    after = store._load_payload()
    assert tuple(a for a in store.load_daily_assignments()
                 if a.completed_at is not None) == completed
    assert not store.load_market_plan_bindings()
    assert not after['active_execution_plan_ids']
    assert after['planning_recovery_history']['market-reset']['previous_state'] == before


def test_recovery_disk_failure_leaves_all_original_state(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    pipeline.run(planning_input=source)
    before = store._path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError('disk full')
    import pytest
    monkeypatch.setattr('picot.v2.plan_commitment_store.os.replace', fail)
    with pytest.raises(OSError):
        store.request_planning_recovery(request_id='disk', requested_at=source.captured_at)
    assert store._path.read_bytes() == before


def test_recovery_does_not_waive_goal_when_inputs_are_missing(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    pipeline.run(planning_input=source)
    store.request_planning_recovery(request_id='missing-prices', requested_at=source.captured_at)
    result = pipeline.run(planning_input=recover(replace(source, price_points=())))
    assert result.evaluation.status == 'fallback_active'
    assert result.evaluation.reason == 'daily_main_planning_data_unavailable'
    assert not store.deferred_recovery_assignment_ids()
    assert all(a.completed_at is None for a in store.load_daily_assignments())
    assert store.daily_recalculation_status()['status'] == 'pending'
