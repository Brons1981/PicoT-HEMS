"""Daily overbridging through the canonical pipeline and durable store."""

from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_daily_main_route_optimisation import fresh
from test_daily_pv_route_optimisation import source_with_later_cheap_window

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def shift(value, delta):
    if isinstance(value, datetime):
        return value + delta
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value, **{f.name: shift(getattr(value, f.name), delta) for f in fields(value)}
        )
    if isinstance(value, tuple):
        return tuple(shift(v, delta) for v in value)
    return value


def started(tmp_path, monkeypatch, conversion=None):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    if conversion is not None:
        pipeline = CanonicalPipeline(
            commitment_store=store,
            market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion),
        )
    original = source_with_later_cheap_window()
    source = fresh(original, pv_factor=0, soc=0.1, tag="today")
    yesterday = fresh(shift(original, -timedelta(days=1)), pv_factor=0, soc=0.1, tag="yesterday")
    previous = pipeline.run(planning_input=recover(yesterday))
    assert previous.execution_plan_set.plans, previous.evaluation.reason
    owner = store.load_daily_assignments()[0]
    segment = owner.main_segments[-1]
    completed = owner.observe_completion(
        measured_at=segment.ends_at,
        soc=1,
        execution_allowed=True,
        plan_id=owner.route_plan_id,
        segment_id=segment.segment_id,
        evidence_id="measured-full",
    )
    assert completed.completed_at is not None
    store.save_daily_assignment(completed)
    initial = pipeline.run(planning_input=recover(source))
    assert initial.execution_plan_set.plans, initial.evaluation.reason
    return store, pipeline, recover, source, completed, initial


def test_direct_grid_winner_is_retained_and_cannot_reopen_completed_goal(tmp_path, monkeypatch):
    store, pipeline, recover, source, completed, initial = started(tmp_path, monkeypatch)
    old = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.daily_bridge.status == "energy_shortfall", result.evaluation.reason
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    from picot.v2.projection import project

    before_projection = (tmp_path / "plans.json").read_bytes()
    cards = project(result).cards
    card = next(c for c in cards if c.entity_id.endswith("04_evaluation_engine"))
    assert len(cards) == 9
    assert card.attributes["daily_bridge"]["status"] == "energy_shortfall"
    assert card.attributes["daily_bridge"]["review_triggered"] is True
    assert (tmp_path / "plans.json").read_bytes() == before_projection
    plan = store.load_active_daily_main_plan("battery")
    assert plan.plan_id != initial.execution_plan_set.plans[0].plan_id
    assert all(
        s.primitive is not ExecutionPrimitive.CHARGE_AT_POWER
        for s in plan.segments
        if s.ends_at <= old.main_segments[0].starts_at
    )
    revised = next(
        a for a in store.load_daily_assignments() if a.assignment_id == old.assignment_id
    )
    assert [(s.starts_at, s.ends_at) for s in revised.main_segments] == [
        (s.starts_at, s.ends_at) for s in old.main_segments
    ]
    assert (
        next(
            a for a in store.load_daily_assignments() if a.assignment_id == completed.assignment_id
        )
        == completed
    )
    assert store.load_daily_bridge_state(old.assignment_id) is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("accepted direct net supply must not rediscover windows")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "bridge_windows", forbidden)
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    pipeline = CanonicalPipeline(
        commitment_store=restarted,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
    )
    repeated = pipeline.run(
        planning_input=_restore_daily_charge_context(
            fresh(source, pv_factor=1, tag="repeat"), restarted, local_timezone=ZoneInfo("UTC")
        )
    )
    assert repeated.evaluation.daily_bridge.status == "accepted_grid_support"
    assert repeated.execution_plan_set.plans[0].plan_id == plan.plan_id


def test_new_cheap_interval_can_fund_bridge_without_moving_main(tmp_path, monkeypatch):
    store, pipeline, recover, source, completed, initial = started(tmp_path, monkeypatch)
    main = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    changed = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.01 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    result = pipeline.run(planning_input=recover(changed))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    bridge = tuple(
        s
        for s in plan.segments
        if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        and s.ends_at <= main.main_segments[0].starts_at
    )
    assert bridge
    assert all(s.main_assignment_id is None for s in bridge)
    assert all(s.starts_at.hour == 11 for s in bridge)
    assert store.load_daily_assignments()[0] == completed


def test_no_next_session_keeps_valid_execution_without_inventing_charge(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch)
    owner = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    segment = owner.main_segments[-1]
    store.save_daily_assignment(
        owner.observe_completion(
            measured_at=segment.ends_at,
            soc=1,
            execution_allowed=True,
            plan_id=owner.route_plan_id,
            segment_id=segment.segment_id,
            evidence_id="today-full",
        )
    )
    at = segment.ends_at + timedelta(seconds=5)
    observation = fresh(source, soc=1, tag="completed")
    observation = replace(
        observation,
        captured_at=at,
        capability_snapshot_set=replace(observation.capability_snapshot_set, captured_at=at),
        current_storage_states=tuple(
            replace(s, measured_at=at) for s in observation.current_storage_states
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("unknown next session must not generate a charge deadline")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "bridge_windows", forbidden)
    result = pipeline.run(planning_input=recover(observation))
    assert result.evaluation.daily_bridge.status == "next_session_unknown"
    assert result.execution_plan_set.plans[0].plan_id == owner.route_plan_id


def test_bridge_write_failure_does_not_partially_replace_plan(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, initial = started(tmp_path, monkeypatch)
    recovered = recover(source)
    before = (tmp_path / "plans.json").read_bytes()

    def failed_write(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "_write", failed_write)
    result = pipeline.run(planning_input=recovered)
    assert result.evaluation.status == "fallback_active"
    assert (tmp_path / "plans.json").read_bytes() == before
    assert (
        store.load_active_daily_main_plan("battery").plan_id
        == initial.execution_plan_set.plans[0].plan_id
    )


def test_bridge_full_measurement_cannot_complete_next_main_goal(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch)
    changed = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.01 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    pipeline.run(planning_input=recover(changed))
    plan = store.load_active_daily_main_plan("battery")
    bridge = next(
        s
        for s in plan.segments
        if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER and s.main_assignment_id is None
    )
    result = store.observe_daily_main_completion(
        execution_scope_id="battery",
        plan_id=plan.plan_id,
        segment_id=bridge.segment_id,
        confirmed_since=bridge.starts_at,
        observed_at=bridge.ends_at,
        measured_at=bridge.ends_at,
        soc=1,
        evidence_id="bridge-full",
    )
    assert result is None
    assert any(a.completed_at is None for a in store.load_daily_assignments())


def test_changed_household_need_reopens_bridge_assessment_only(tmp_path, monkeypatch):
    store, pipeline, recover, source, completed, _ = started(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover(source))
    owner = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    changed = replace(
        source,
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(i, expected_energy_wh=i.expected_energy_wh * 2)
                if i.ends_at <= owner.main_segments[0].starts_at
                else i
                for i in source.household_load_forecast.intervals
            ),
        ),
    )
    result = pipeline.run(planning_input=recover(changed))
    assert result.evaluation.daily_bridge.trigger is not None
    assert result.evaluation.daily_main_shortfall is None
    assert store.load_daily_assignments()[0] == completed
    assert (
        next(
            a for a in store.load_daily_assignments() if a.assignment_id == owner.assignment_id
        ).revision
        == owner.revision + 1
    )


def test_corrupt_bridge_state_blocks_recovery_without_erasing_route(tmp_path, monkeypatch):
    import json

    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover(source))
    plan = store.load_active_daily_main_plan("battery")
    path = tmp_path / "plans.json"
    payload = json.loads(path.read_text())
    payload["daily_bridge_states"] = ["invalid"]
    path.write_text(json.dumps(payload))
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "fallback_active"
    assert "saved bridge assessment is invalid" in result.evaluation.reason
    assert store.load_active_daily_main_plan("battery") == plan


def test_bridge_dispatch_uses_existing_clock_and_explicit_power(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import with_mode

    from picot.v2.canonical_execution_runtime import (
        CanonicalDispatchOutcome,
        CanonicalExecutionRuntime,
    )

    store, pipeline, recover, source, completed, _ = started(tmp_path, monkeypatch)
    changed = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.01 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    pipeline.run(planning_input=recover(changed))
    plan = store.load_active_daily_main_plan("battery")
    bridge = next(
        s
        for s in plan.segments
        if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER and s.main_assignment_id is None
    )
    observation = with_mode(
        replace(
            source,
            captured_at=bridge.starts_at,
            capability_snapshot_set=replace(
                source.capability_snapshot_set, captured_at=bridge.starts_at
            ),
        ),
        bridge.primitive,
    )
    requests = []

    def dispatch(request, mapping):
        requests.append(request)
        return CanonicalDispatchOutcome("dispatched", "test-only-command")

    runtime = CanonicalExecutionRuntime(dispatch, commitment_store=store)
    result = runtime.advance_committed_boundary(recover(observation), execution_enabled=True)
    assert result.status == "dispatched"
    assert requests[0].plan_id == plan.plan_id
    assert requests[0].segment_id == bridge.segment_id
    assert requests[0].requested_power_w == 2400
    assert store.load_daily_assignments()[0] == completed


def test_roundtrip_losses_can_make_direct_grid_cheaper_than_precharging(tmp_path, monkeypatch):
    conversion = replace(
        inputs()["conversion_model"], charge_efficiency=0.9, discharge_efficiency=0.9
    )
    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch, conversion)
    main = next(a for a in store.load_daily_assignments() if a.completed_at is None)
    changed = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.49 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    result = pipeline.run(planning_input=recover(changed))
    assert result.evaluation.daily_bridge.trigger is not None
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    # 0.49 / (0.9 * 0.9) > 0.50 EUR per delivered kWh, despite cheaper input.
    assert not any(
        s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        and s.ends_at <= main.main_segments[0].starts_at
        for s in plan.segments
    )


def test_sufficient_energy_keeps_plan_without_price_search(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, initial = started(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("sufficient reserve must not search price windows")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "bridge_windows", forbidden)
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", forbidden)
    result = pipeline.run(planning_input=recover(fresh(source, soc=0.7, tag="enough-energy")))
    assert result.evaluation.daily_bridge.status == "sufficient"
    assert result.execution_plan_set.plans[0].plan_id == initial.execution_plan_set.plans[0].plan_id


def test_changed_household_forecast_triggers_live_poll_without_soc_change(tmp_path, monkeypatch):
    from test_daily_charge_runtime_input import bundle

    from picot.v2.live_runtime import _planning_input_signature

    _, _, recover = setup(tmp_path, monkeypatch)
    source = recover(source_with_later_cheap_window())
    original = _planning_input_signature(bundle(source))
    changed = replace(
        source,
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(i, expected_energy_wh=i.expected_energy_wh + 100)
                for i in source.household_load_forecast.intervals
            ),
        ),
    )
    assert source.current_storage_states == changed.current_storage_states
    assert _planning_input_signature(bundle(changed)) != original
    missing = replace(source, household_load_forecast=None)
    assert _planning_input_signature(bundle(missing)) != original
