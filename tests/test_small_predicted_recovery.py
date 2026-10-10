"""Small forecast discrepancies defer only with a real later recovery path."""
from dataclasses import replace

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.household_load_guard import HouseholdLoadGuardAssessment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def household_bridge(tmp_path, *, quarter_wh=118.5):
    _, snapshot, plan = scenario(tmp_path, soc=1)
    context = snapshot.daily_charge_context
    plan = replace(plan, segments=tuple(
        replace(s, primitive=Primitive.BALANCE_DISCHARGE_ONLY,
                requested_power_w=None, purpose="retained-route")
        if s.primitive is Primitive.DISCHARGE_AT_POWER else s
        for s in plan.segments
    ))
    return replace(snapshot,
        household_load_forecast=replace(snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=quarter_wh)
            for i in snapshot.household_load_forecast.intervals)),
        daily_charge_context=replace(context, market_plan_bindings=(), main_plans=tuple(
            plan if p.plan_id == plan.plan_id else p for p in context.main_plans)),
    )


def test_small_morning_shortage_waits_without_completing_or_reopening_day(tmp_path):
    snapshot = household_bridge(tmp_path)
    context = snapshot.daily_charge_context
    adapter = IndependentDailyReferenceAdapter()
    assessment = adapter.bridge_assessment(snapshot=snapshot,
                                           conversion_model=inputs()["conversion_model"])
    assert sum(i.deficit_wh for i in assessment.deficits) == pytest.approx(240)
    assert assessment.status == "deferred_with_recovery"
    assert assessment.trigger is None
    assert snapshot.daily_charge_context == context
    assert snapshot.current_storage_states[0].current_soc == 1
    assert any(a.completed_at is not None for a in context.assignments)
    assert any(a.completed_at is None for a in context.assignments)


def test_large_shortage_and_unknown_measurements_are_not_deferred(tmp_path):
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    large = household_bridge(tmp_path, quarter_wh=120)
    result = adapter.bridge_assessment(snapshot=large, conversion_model=conversion)
    assert sum(i.deficit_wh for i in result.deficits) == pytest.approx(336)
    assert result.trigger is not None
    small = household_bridge(tmp_path / "small")
    unknown = replace(small, household_load_guard=HouseholdLoadGuardAssessment(
        True, "unknown", 0, small.captured_at))
    assert adapter.bridge_assessment(snapshot=unknown, conversion_model=conversion).trigger
    slow = replace(conversion, charge_efficiency=0.01)
    assert adapter.bridge_assessment(snapshot=small, conversion_model=slow).trigger


def test_current_shortage_cannot_wait_even_when_small(tmp_path):
    snapshot = household_bridge(tmp_path)
    snapshot = replace(snapshot,
        current_storage_states=tuple(replace(s, current_soc=0.1)
                                     for s in snapshot.current_storage_states),
        household_load_forecast=replace(snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=200 if n == 0 else 0)
            for n, i in enumerate(snapshot.household_load_forecast.intervals))),
    )
    assessment = IndependentDailyReferenceAdapter().bridge_assessment(
        snapshot=snapshot, conversion_model=inputs()["conversion_model"])
    assert sum(i.deficit_wh for i in assessment.deficits) == pytest.approx(200)
    assert assessment.trigger is not None


def test_bridge_with_no_storage_acquisition_uses_standby_not_latent_refill(tmp_path):
    snapshot = household_bridge(tmp_path, quarter_wh=120)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    assessment = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion)
    windows = adapter.bridge_windows(snapshot=snapshot, trigger=assessment.trigger,
                                     conversion_model=conversion)
    assert windows.windows
    first_main = assessment.next_starts_at
    saw_direct_support = False
    for window in windows.windows:
        for intent, actual in zip(
            window.schedule.intervals, window.projection.intervals, strict=True,
        ):
            if intent.ends_at > first_main:
                continue
            acquired = actual.grid_to_storage_input_wh + actual.pv_to_storage_input_wh
            if intent.intent is Intent.GRID_REQUIREMENT:
                assert acquired > 1e-6
            if intent.intent is Intent.STANDBY and actual.storage_energy_at_start_wh == 8160:
                saw_direct_support = True
    assert saw_direct_support


def test_deferred_bridge_stays_in_canonical_plan_through_restart(tmp_path):
    from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
    from picot.v2.pipeline import CanonicalPipeline
    from picot.v2.plan_commitment_store import (
        ActivePlanCommitmentStore,
        _serialize_daily,
        _serialize_execution_plan,
    )
    snapshot = replace(household_bridge(tmp_path), market_user_rule=None)
    context = snapshot.daily_charge_context
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in context.assignments},
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(context.main_plans[0])
                               for a in context.assignments},
        execution_plans={p.plan_id: _serialize_execution_plan(p) for p in context.main_plans},
        market_plan_bindings={},
        active_execution_plan_ids={"battery": context.active_main_plan_ids[0]},
    )
    store._write(payload)
    before = store.load_daily_assignments()
    for _ in range(2):
        store = ActivePlanCommitmentStore(tmp_path / "plans.json")
        pipeline = CanonicalPipeline(commitment_store=store,
            market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]))
        result = pipeline.run(planning_input=snapshot)
        assert result.evaluation.daily_bridge.status == "deferred_with_recovery"
        assert result.evaluation.status == "plan_retained", result.evaluation.reason
        assert result.execution_plan_set.plans[0].plan_id == context.active_main_plan_ids[0]
        assert store.load_daily_assignments() == before
        assert not any(s.primitive is Primitive.CHARGE_AT_POWER
                       and s.starts_at >= snapshot.captured_at
                       and s.ends_at <= result.evaluation.daily_bridge.next_starts_at
                       for s in result.execution_plan_set.plans[0].segments)


def test_main_revision_reassesses_old_bridge_without_unowned_refill(tmp_path):
    from picot.v2.daily_charge_assignment import DailyMainShortfallTrigger

    snapshot = household_bridge(tmp_path, quarter_wh=100)
    context = snapshot.daily_charge_context
    owner = next(a for a in context.assignments if a.completed_at is None)
    plan = context.main_plans[0]
    old_bridge = next(s for s in plan.segments
                      if s.starts_at <= snapshot.captured_at < s.ends_at)
    bridge = replace(old_bridge, primitive=Primitive.CHARGE_AT_POWER, requested_power_w=2400,
                     purpose=f"bridge:{owner.assignment_id}")
    plan = replace(plan, segments=tuple(
        bridge if s == old_bridge else
        replace(s, primitive=Primitive.BALANCE_BIDIRECTIONAL)
        if s.starts_at == old_bridge.ends_at else s for s in plan.segments))
    snapshot = replace(snapshot, daily_charge_context=replace(context, main_plans=(plan,)))
    trigger = DailyMainShortfallTrigger(
        owner.assignment_id, owner.route_plan_id, owner.revision, plan.plan_id,
        snapshot.snapshot_id, snapshot.captured_at, 7800, 8160,
    )
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=owner, conversion_model=inputs()["conversion_model"],
        optimisation_trigger=trigger,
    )
    assert windows.windows
    assert all(i.intent is not Intent.GRID_REQUIREMENT
               for w in windows.windows for i in w.schedule.intervals
               if snapshot.captured_at <= i.starts_at and i.ends_at <= old_bridge.ends_at)
    assert all(a.completed_at is not None for a in context.assignments if a != owner)

    from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, opportunity_ids=("prices",),
        tariffs=IndependentDailyTariffAdapter().build(
            snapshot, horizon_end=windows.windows[0].schedule.horizon_end),
    )
    assert portfolio.candidate_set.energy_paths
    assert all(any(s.purpose == f"bridge:{owner.assignment_id}"
                   and s.starts_at == snapshot.captured_at and s.ends_at == old_bridge.ends_at
                   for s in path.segments) for path in portfolio.candidate_set.energy_paths)
    from picot.planner.evaluation_engine import EvaluationEngine
    from picot.planner.execution_plan_builder import ExecutionPlanBuilder

    selected = EvaluationEngine().evaluate(
        portfolio.candidate_set, portfolio.strategy, portfolio.outcome_set,
        created_at=snapshot.captured_at,
    )
    built = ExecutionPlanBuilder().build(selected, created_at=snapshot.captured_at,
                                        fallback_policy_id="guarded-nom")
    assert len(built.plans) == 1
    first = built.plans[0].segments[0]
    assert first.purpose == f"bridge:{owner.assignment_id}"
    assert first.ends_at == old_bridge.ends_at
    assert first.primitive is Primitive.BALANCE_BIDIRECTIONAL


def test_reset_does_not_reuse_future_commands_from_completed_day(tmp_path):
    snapshot = household_bridge(tmp_path)
    context = snapshot.daily_charge_context
    owner = next(a for a in context.assignments if a.completed_at is None)
    completed = next(a for a in context.assignments if a.completed_at is not None)
    # Reset tomorrow's binding, retaining today's immutable completion proof.
    owner = replace(owner, route_plan_id=None, main_segments=(), revision=0,
                    revised_at=None, revision_reason=None, revision_evidence_id=None)
    context = replace(context, active_main_plan_ids=(), assignments=tuple(
        owner if a.completed_at is None else a for a in context.assignments))
    snapshot = replace(snapshot, daily_charge_context=context)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    with_history = adapter.main_charge_windows(
        snapshot=snapshot, assignment=owner, conversion_model=conversion)
    without_history = adapter.main_charge_windows(
        snapshot=replace(snapshot, daily_charge_context=replace(context, main_plans=tuple(
            replace(p, segments=tuple(replace(s, primitive=Primitive.BALANCE_DISCHARGE_ONLY,
                requested_power_w=None, charge_source_policy=None)
                if s.starts_at >= snapshot.captured_at else s for s in p.segments))
            for p in context.main_plans))),
        assignment=owner, conversion_model=conversion)
    assert with_history.windows and without_history.windows
    assert {w.schedule.intervals for w in with_history.windows} == {
        w.schedule.intervals for w in without_history.windows}
    assert next(a for a in snapshot.daily_charge_context.assignments
                if a.completed_at is not None) == completed
