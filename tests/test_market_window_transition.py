"""Unstarted legacy export is released through Candidate/Evaluation/Builder/Store."""
from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_market_rule_selection import trading_source, with_next_day_recovery

from picot.domain.energy_path import RetainedExecutionOrigin
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_execution import MarketExecutionProgress
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.planner.market_route_admission import MarketAdmission
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def legacy_morning(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = with_next_day_recovery(trading_source(recover()))
    pipeline.run(planning_input=recover(source))
    pipeline.run(planning_input=recover(source))
    original = store.load_active_daily_main_plan("battery")
    day = max(store.load_daily_assignments(), key=lambda a: a.delivery_date)
    start = day.starts_at + timedelta(hours=5)
    end = start + timedelta(minutes=30)
    market = store.ensure_market_daily_assignment(MarketDailyAssignment(
        source.market_user_rule, "battery", day.delivery_date, day.timezone,
        source.captured_at, 8160))
    segments = []
    for old in original.segments:
        cuts = sorted({old.starts_at, old.ends_at,
                       *(t for t in (start, end) if old.starts_at < t < old.ends_at)})
        for left, right in zip(cuts, cuts[1:], strict=False):
            trade = left == start and right == end
            part = replace(old, segment_id=f"legacy:{len(segments)}", order=len(segments) + 1,
                starts_at=left, ends_at=right, retained_execution_origin=(
                    old.retained_execution_origin or RetainedExecutionOrigin(original.plan_id,
                                                                            old.segment_id)
                    if old.main_assignment_id else old.retained_execution_origin))
            if trade:
                assert old.main_assignment_id is None
                part = replace(part, primitive=Primitive.DISCHARGE_AT_POWER,
                               purpose=market.assignment_id, requested_power_w=2400,
                               charge_source_policy=None)
            segments.append(part)
    plan = replace(original, plan_id="legacy-morning", segments=tuple(segments))
    parts = tuple(s for s in plan.segments if s.purpose == market.assignment_id)
    assert len(parts) == 1
    binding = MarketPlanBinding(market.assignment_id, "battery", plan.plan_id,
                                plan.snapshot_id, (parts[0].segment_id,), 500, (500,), 600)
    store.bind_market_plan(plan=plan, previous_plan_id=original.plan_id, binding=binding,
                          admission=MarketAdmission(market.assignment_id, plan.snapshot_id,
                                                    "admissible", "legacy fixture", 500))
    return store, pipeline, recover, source, binding


def test_release_restart_and_wait_preserve_same_day_budget_and_charge(tmp_path, monkeypatch):
    store, pipeline, recover, source, binding = legacy_morning(tmp_path, monkeypatch)
    goals = store.load_daily_assignments()
    market = store.load_market_daily_assignments()
    old = store.load_active_daily_main_plan("battery")
    run = pipeline.run(planning_input=recover(source))
    assert run.evaluation.reason == "market_window_transition_waits_for_evening_admission"
    new = store.load_active_daily_main_plan("battery")
    assert new.plan_id != old.plan_id
    assert not any(s.purpose == binding.assignment_id for s in new.segments)
    assert store.load_daily_assignments() == goals
    assert store.load_market_daily_assignments() == market
    assert store.market_transition_export_limit(binding.assignment_id) == 500
    restarted = ActivePlanCommitmentStore(store._path)
    assert restarted.load_active_daily_main_plan("battery") == new
    assert restarted.pending_market_window_transition(source.captured_at) is None
    waiting = pipeline.run(planning_input=recover(source))
    assert waiting.evaluation.reason != "market_window_transition_waits_for_evening_admission"
    assert all(b.assignment_id != binding.assignment_id for b in store.load_market_plan_bindings())
    assert next(a for a in store.load_market_daily_assignments()
                if a.assignment_id == binding.assignment_id).status == "pending"


@pytest.mark.parametrize("begun", [True, False])
def test_begun_or_stopped_trade_is_never_released(tmp_path, monkeypatch, begun):
    store, _, _, source, binding = legacy_morning(tmp_path, monkeypatch)
    store.save_market_progress(MarketExecutionProgress(binding.assignment_id,
        started_at=source.captured_at if begun else None,
        stop_requested_at=None if begun else source.captured_at,
        reason=None if begun else "test stop"))
    assert store.pending_market_window_transition(source.captured_at) is None


def test_failed_transition_write_keeps_original_budget_and_plan(tmp_path, monkeypatch):
    store, pipeline, recover, source, binding = legacy_morning(tmp_path, monkeypatch)
    before = store._path.read_bytes()
    write = store._write

    def fail(payload):
        if payload.get("market_window_transitions"):
            raise OSError("transition-write-failed")
        write(payload)

    monkeypatch.setattr(store, "_write", fail)
    run = pipeline.run(planning_input=recover(source))
    assert "transition-write-failed" in run.evaluation.reason
    assert store._path.read_bytes() == before
    assert store.pending_market_window_transition(source.captured_at) == binding


def test_transition_retry_and_archive_tamper_detection(tmp_path, monkeypatch):
    import json

    store, pipeline, recover, source, binding = legacy_morning(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover(source))
    assert run.evaluation.status == "winner_selected"
    saved = store._path.read_bytes()
    # A second request cannot repeat the release or mint another budget.
    assert store.pending_market_window_transition(source.captured_at) is None
    assert store._path.read_bytes() == saved
    payload = json.loads(saved)
    payload["market_window_transitions"][binding.assignment_id]["maximum_export_wh"] += 1
    store._write(payload)
    with pytest.raises(ValueError, match="lineage or budget"):
        ActivePlanCommitmentStore(store._path).load_active_daily_main_plan("battery")


def test_tomorrow_morning_waits_even_when_its_price_is_highest(tmp_path, monkeypatch):
    from test_daily_main_charge_windows import inputs

    from picot.v2.market_rule_planning import market_rule_portfolio

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = with_next_day_recovery(trading_source(recover()))
    source = replace(source, price_points=tuple(
        replace(p, value_eur_per_kwh=2.0)
        if p.starts_at.date() > source.captured_at.date() and p.starts_at.hour == 7 else p
        for p in source.price_points))
    pipeline.run(planning_input=recover(source))
    pipeline.run(planning_input=recover(source))
    day = max(store.load_daily_assignments(), key=lambda a: a.delivery_date)
    assignment = MarketDailyAssignment(source.market_user_rule, "battery", day.delivery_date,
                                      day.timezone, source.captured_at, 8160)
    before = store._path.read_bytes()
    with pytest.raises(ValueError, match="future_owned_charge_does_not_prove_full_recovery"):
        market_rule_portfolio(snapshot=recover(source),
            plan=store.load_active_daily_main_plan("battery"), assignment=assignment,
            conversion=inputs()["conversion_model"], opportunity_ids=())
    assert store._path.read_bytes() == before


def test_replacement_cannot_exceed_released_export_budget(tmp_path, monkeypatch):
    store, pipeline, recover, source, binding = legacy_morning(tmp_path, monkeypatch)
    original = store.load_market_bound_plan(binding.assignment_id)
    run = pipeline.run(planning_input=recover(source))
    assert run.evaluation.status == "winner_selected"
    current = store.load_active_daily_main_plan("battery")
    proposed = replace(original, plan_id="attempt-extra-budget")
    enlarged = replace(binding, plan_id=proposed.plan_id,
                       expected_export_wh=600, segment_export_wh=(600,))
    before = store._path.read_bytes()
    with pytest.raises(ValueError, match="cannot replenish"):
        store.bind_market_plan(plan=proposed, previous_plan_id=current.plan_id, binding=enlarged,
            admission=MarketAdmission(binding.assignment_id, proposed.snapshot_id,
                                      "admissible", "budget-boundary-test", 600))
    assert store._path.read_bytes() == before
