from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_daily_main_active_pipeline import setup

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_user_rule import MarketUserRule
from picot.planner.market_export_windows import ExportCapacityPart, export_windows


def test_physical_window_uses_household_power_and_both_price_boundaries():
    start = datetime(2026, 9, 9, 12, tzinfo=UTC)
    parts = tuple(
        ExportCapacityPart(start + timedelta(hours=i), start + timedelta(hours=i + 1), 1800)
        for i in range(2)
    )
    windows = export_windows(parts, 1200)
    assert any(
        w[0].starts_at == start and w[-1].ends_at == start + timedelta(minutes=40) for w in windows
    )
    assert any(
        w[-1].ends_at == start + timedelta(hours=1)
        and w[0].starts_at == start + timedelta(minutes=20)
        for w in windows
    )
    assert all(sum(p.energy_wh for p in w) == pytest.approx(1200) for w in windows)


def test_protected_charge_window_is_never_crossed():
    start = datetime(2026, 9, 9, 12, tzinfo=UTC)
    parts = (
        ExportCapacityPart(start, start + timedelta(minutes=15), 2400),
        ExportCapacityPart(start + timedelta(minutes=30), start + timedelta(minutes=45), 2400),
    )
    assert export_windows(parts, 1000) == ()


def trading_source(source):
    start = source.captured_at.replace(hour=0, minute=0, second=0, microsecond=0)
    price_points = tuple(
        replace(
            source.price_points[0],
            starts_at=start + timedelta(minutes=15 * n),
            ends_at=min(start + timedelta(minutes=15 * (n + 1)), source.price_points[-1].ends_at),
            value_eur_per_kwh=0.8 if (start + timedelta(minutes=15 * n)).hour == 15 else 0.1,
        )
        for n in range(int((source.price_points[-1].ends_at - start).total_seconds() / 900))
    )
    return replace(
        source,
        market_user_rule=MarketUserRule("user-market", 1, 0.1, 0),
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            capabilities=tuple(
                replace(
                    c,
                    supported_primitives=(
                        *c.supported_primitives,
                        ExecutionPrimitive.DISCHARGE_AT_POWER,
                    ),
                )
                for c in source.capability_snapshot_set.capabilities
            ),
        ),
        price_points=price_points,
    )


def test_real_pipeline_selects_trade_and_keeps_charge_identity(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(trading_source(recover()))
    first = pipeline.run(planning_input=source)
    assert first.execution_plan_set.plans, first.evaluation.reason
    original = store.load_active_daily_main_plan("battery")
    owners = store.load_daily_assignments()
    second = pipeline.run(planning_input=recover(source))
    assert second.evaluation.reason == "user_market_rule_selected", second.evaluation.reason
    bindings = store.load_market_plan_bindings()
    assert len(bindings) == 1
    shared = store.load_active_daily_main_plan("battery")
    assert shared.plan_id != original.plan_id
    assert store.load_daily_assignments() == owners
    assert bindings[0].plan_id == shared.plan_id
    assert any(s.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER for s in shared.segments)


def test_market_uses_full_publication_after_live_input_removes_elapsed_quarters(
    tmp_path, monkeypatch,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = trading_source(recover())
    source = replace(
        source,
        published_price_points=source.price_points,
        price_points=tuple(p for p in source.price_points if p.ends_at > source.captured_at),
    )
    assert len(source.price_points) < len(source.published_price_points)
    first = pipeline.run(planning_input=recover(source))
    assert first.execution_plan_set.plans
    owners = store.load_daily_assignments()
    second = pipeline.run(planning_input=recover(source))
    assert second.evaluation.reason == "user_market_rule_selected", second.evaluation.reason
    assert store.load_daily_assignments() == owners
    assert all(
        s.starts_at >= source.captured_at
        for s in store.load_active_daily_main_plan("battery").segments
        if s.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
    )


def winter_source(source):
    source = trading_source(source)
    return replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=tuple(
                replace(
                    p,
                    pv_energy_wh=0,
                    forecast_lower_energy_wh=0,
                    forecast_central_energy_wh=0,
                    forecast_upper_energy_wh=0,
                )
                for p in source.pv_energy_timeline.intervals
            ),
        ),
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(h, expected_energy_wh=0) for h in source.household_load_forecast.intervals
            ),
        ),
        price_points=tuple(
            replace(
                p,
                value_eur_per_kwh=0.01
                if p.starts_at.hour == 20
                else 0.8
                if p.starts_at.hour == 15
                else 0.2,
            )
            for p in source.price_points
        ),
    )


def test_trade_adds_cheapest_required_charge_before_atomic_publication(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    first = pipeline.run(planning_input=source)
    assert first.execution_plan_set.plans, first.evaluation.reason
    original = store.load_active_daily_main_plan("battery")
    owner = next(a for a in store.load_daily_assignments() if a.route_plan_id == original.plan_id)
    second = pipeline.run(planning_input=recover(source))
    assert second.evaluation.reason == "user_market_rule_selected", second.evaluation.reason
    revised = next(
        a for a in store.load_daily_assignments() if a.assignment_id == owner.assignment_id
    )
    assert revised.revision == owner.revision + 1
    assert revised.completed_at is None
    bindings = store.load_market_plan_bindings()
    assert len(bindings) == 1
    assert revised.route_plan_id == bindings[0].plan_id
    assert sum((s.ends_at - s.starts_at).total_seconds() for s in revised.main_segments) > sum(
        (s.ends_at - s.starts_at).total_seconds() for s in owner.main_segments
    )
    assert any(
        s.starts_at.hour == 20 or s.starts_at.hour < 20 < s.ends_at.hour
        for s in revised.main_segments
    )


def test_soc_optimisation_during_trade_keeps_original_window_and_budget(tmp_path, monkeypatch):
    from picot.domain.market_execution import MarketExecutionProgress

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    pipeline.run(planning_input=source)
    selected = pipeline.run(planning_input=recover(source))
    assert selected.evaluation.reason == "user_market_rule_selected", selected.evaluation.reason
    original_binding = store.load_market_plan_bindings()[0]
    original = store.load_market_bound_plan(original_binding.assignment_id)
    trade = tuple(s for s in original.segments if s.segment_id in original_binding.segment_ids)
    at = trade[0].starts_at + timedelta(minutes=5)
    store.save_market_progress(
        MarketExecutionProgress(
            original_binding.assignment_id, started_at=trade[0].starts_at, measured_export_wh=100
        )
    )
    changed = replace(
        source,
        captured_at=at,
        daily_charge_context=None,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        current_storage_states=tuple(
            replace(s, current_soc=0.2, measured_at=at) for s in source.current_storage_states
        ),
    )
    run = pipeline.run(planning_input=recover(changed))
    assert run.evaluation.status == "winner_selected", run.evaluation.reason
    bound = store.load_market_plan_bindings()[0]
    assert bound.assignment_id == original_binding.assignment_id
    assert bound.expected_export_wh == original_binding.expected_export_wh
    assert bound.elapsed_planned_export_wh > 0
    assert sum(bound.segment_export_wh) < bound.expected_export_wh
    current = store.load_market_bound_plan(bound.assignment_id)
    remaining = tuple(s for s in current.segments if s.segment_id in bound.segment_ids)
    assert remaining[0].starts_at == at
    assert remaining[-1].ends_at == trade[-1].ends_at
    assert store.load_market_original_plan(bound) == original
    assert len(store.load_market_daily_assignments()) == 1


def test_combined_write_failure_preserves_charge_and_does_not_publish_trade(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover(winter_source(recover()))
    pipeline.run(planning_input=source)
    original = store.load_active_daily_main_plan("battery")
    owners = store.load_daily_assignments()
    write = store._write

    def fail_combined(payload):
        if payload.get("market_plan_bindings"):
            raise OSError("combined-write-failed")
        write(payload)

    monkeypatch.setattr(store, "_write", fail_combined)
    result = pipeline.run(planning_input=recover(source))
    assert "combined-write-failed" in result.evaluation.reason
    assert store.load_active_daily_main_plan("battery") == original
    assert store.load_daily_assignments() == owners
    assert store.load_market_plan_bindings() == ()


def test_recovery_option_evaluates_combined_charge_and_trade(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = winter_source(recover())
    source = recover(
        replace(
            source,
            market_user_rule=replace(
                source.market_user_rule,
                recovery_required=True,
                minimum_net_margin_eur_per_export_kwh=0.05,
            ),
        )
    )
    pipeline.run(planning_input=source)
    selected = pipeline.run(planning_input=recover(source))
    assert selected.evaluation.reason == "user_market_rule_selected", selected.evaluation.reason
    binding = store.load_market_plan_bindings()[0]
    assert store.load_market_daily_assignments()[0].rule.recovery_required
    plan = store.load_market_bound_plan(binding.assignment_id)
    exports = [s for s in plan.segments if s.purpose == binding.assignment_id]
    goals = [a for a in store.load_daily_assignments() if a.route_plan_id == plan.plan_id]
    assert any(seg.ends_at > exports[-1].ends_at for a in goals for seg in a.main_segments)
