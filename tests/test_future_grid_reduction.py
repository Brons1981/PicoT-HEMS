"""Future-day reduction uses measured stock without claiming future PV actuals."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.daily_pv_comparison import DailyPVComparisonBasis
from picot.v2.household_load_guard import HouseholdLoadGuardAssessment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.material_replanning import daily_grid_review_comparison
from picot.v2.pipeline import CanonicalPipeline


def future_case(tmp_path):
    store, snapshot, plan = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot, household_load_forecast=replace(
        snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=50) for i in snapshot.household_load_forecast.intervals)))
    owner = next(a for a in snapshot.daily_charge_context.assignments if a.completed_at is None)
    basis = DailyPVComparisonBasis.capture(snapshot, type(owner)(
        owner.execution_scope_id, owner.delivery_date, owner.timezone, owner.created_at))
    payload = store._load_payload()
    payload['daily_pv_comparison'] = {owner.assignment_id: {'basis': basis.to_payload(),
                                                         'assessed': {}}}
    store._write(payload)
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo('Europe/Amsterdam'))
    state = next(s for s in snapshot.daily_charge_context.pv_comparison_states
                 if s.assignment_id == owner.assignment_id)
    return store, snapshot, plan, owner, state


def test_future_stock_review_uses_real_pipeline_and_preserves_completed_owner(tmp_path):
    store, snapshot, old, owner, state = future_case(tmp_path)
    comparison = daily_grid_review_comparison(snapshot, state)
    assert comparison.status == 'no_closed_interval'
    adapter = IndependentDailyReferenceAdapter()
    trigger = adapter.pv_surplus_trigger(snapshot=snapshot, assignment=owner,
        comparison=comparison, conversion_model=inputs()['conversion_model'])
    assert trigger is not None
    assert trigger.future_state_evidence_id
    assert trigger.actual_wh is None and trigger.central_wh is None
    completed = next(a for a in store.load_daily_assignments() if a.completed_at is not None)
    run = CanonicalPipeline(commitment_store=store, market_daily_planner_runtime=
        MarketDailyPlannerRuntime(inputs()['conversion_model'])).run(planning_input=snapshot)
    assert run.evaluation.daily_pv_surplus_trigger is not None, run.evaluation.reason
    assert store.load_daily_assignments()[0] == completed
    assert run.evaluation.status in {'winner_selected', 'plan_retained'}
    assert trigger.comparison_evidence_id in store.load_daily_pv_comparison(
        owner.assignment_id).assessed_evidence_ids


@pytest.mark.parametrize('change', ['stale', 'running', 'completed'])
def test_future_review_cannot_reopen_running_owner_or_use_stale_stock(tmp_path, change):
    _, snapshot, _, owner, state = future_case(tmp_path)
    comparison = daily_grid_review_comparison(snapshot, state)
    if change == 'stale':
        snapshot = replace(snapshot, current_storage_states=tuple(
            replace(s, measured_at=s.measured_at - timedelta(minutes=3))
            for s in snapshot.current_storage_states))
    elif change == 'running':
        snapshot = replace(snapshot, captured_at=owner.main_segments[0].starts_at,
                           daily_charge_context=None, capability_snapshot_set=None,
                           storage_mode_capability_evidence=None, active_plan_commitments=())
    else:
        owner = replace(owner, completed_at=owner.main_segments[0].starts_at,
                        completion_evidence_id='measured-full',
                        completion_segment_id=owner.main_segments[0].segment_id)
    assert not IndependentDailyReferenceAdapter().grid_review_available(snapshot, owner, comparison)


def test_ev_exclusion_changes_review_evidence_without_poll_timestamp_churn(tmp_path):
    _, snapshot, _, _, state = future_case(tmp_path)
    first = daily_grid_review_comparison(snapshot, state)
    excluded = replace(snapshot, household_load_forecast=replace(snapshot.household_load_forecast,
        intervals=tuple(replace(i, battery_excluded_energy_wh=i.expected_energy_wh)
                        for i in snapshot.household_load_forecast.intervals)))
    assert daily_grid_review_comparison(excluded, state).evidence_id != first.evidence_id
    refreshed = replace(snapshot, current_storage_states=tuple(
        replace(s, measured_at=s.measured_at - timedelta(seconds=1))
        for s in snapshot.current_storage_states))
    assert daily_grid_review_comparison(refreshed, state).evidence_id == first.evidence_id


@pytest.mark.parametrize('active', [False, True])
@pytest.mark.parametrize('soc', [0.98, 1.0])
def test_fresh_read_with_old_value_and_inactive_unknown_guard(tmp_path, active, soc):
    _, snapshot, _, owner, state = future_case(tmp_path)
    snapshot = replace(snapshot, current_storage_states=tuple(replace(
        s, current_soc=soc, measured_at=snapshot.captured_at - timedelta(hours=1),
        state_valid_since=snapshot.captured_at - timedelta(hours=1),
        state_read_at=snapshot.captured_at) for s in snapshot.current_storage_states),
        household_load_guard=HouseholdLoadGuardAssessment(active, 'unknown', 0,
                                                         snapshot.captured_at, None))
    trigger = IndependentDailyReferenceAdapter().pv_surplus_trigger(
        snapshot=snapshot, assignment=owner,
        comparison=daily_grid_review_comparison(snapshot, state),
        conversion_model=inputs()['conversion_model'])
    assert (trigger is not None) is (not active)


def test_full_battery_now_does_not_zero_future_refill_financial_benefit(tmp_path):
    _, snapshot, _, owner, state = future_case(tmp_path)
    snapshot = replace(snapshot, current_storage_states=tuple(
        replace(s, current_soc=1.0) for s in snapshot.current_storage_states))
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()['conversion_model']
    trigger = adapter.pv_surplus_trigger(snapshot=snapshot, assignment=owner,
        comparison=daily_grid_review_comparison(snapshot, state), conversion_model=conversion)
    assert trigger is not None and trigger.future_state_evidence_id
    windows = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
        conversion_model=conversion, optimisation_trigger=trigger)
    horizon = windows.windows[0].schedule.horizon_end
    incumbent = adapter.main_charge_incumbent(snapshot=snapshot, assignment=owner,
        conversion_model=conversion, horizon_end=horizon)
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=horizon)
    portfolio = produce_main_charge_portfolio(snapshot=snapshot, windows=windows, tariffs=tariffs,
        opportunity_ids=('future-stock',), incumbent=incumbent, future_state_trigger=trigger)
    old = produce_main_charge_portfolio(snapshot=snapshot, windows=windows, tariffs=tariffs,
        opportunity_ids=('future-stock',), incumbent=incumbent)
    assert all(o.commitment_improvement_eur in (0, None) for o in old.outcome_set.outcomes)
    first_grid = min(s.starts_at for s in incumbent.main_segments
                     if s.intent is DailyStorageIntent.GRID_REQUIREMENT)
    stock = next(i.storage_energy_at_start_wh for i in incumbent.projection.intervals
                 if i.starts_at == first_grid)
    deficit_kwh = (8160 - stock) / 1000
    assert deficit_kwh > 0
    reference = next(o for o in portfolio.outcome_set.outcomes
                     if o.candidate_id == portfolio.incumbent_candidate_id)
    reference_rate = next(o.value for o in reference.objective_outcomes
                          if o.objective.value == 'financial_result')
    beneficial = [o for o in portfolio.outcome_set.outcomes
                  if o.commitment_improvement_eur is not None
                  and o.commitment_improvement_eur > 0.01]
    assert beneficial
    for outcome in beneficial:
        rate = next(o.value for o in outcome.objective_outcomes
                    if o.objective.value == 'financial_result')
        assert outcome.commitment_improvement_eur == pytest.approx(
            (reference_rate - rate) * deficit_kwh)
