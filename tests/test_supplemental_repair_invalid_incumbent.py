"""A failed daily goal cannot set the required ending inventory of its repair."""

from dataclasses import replace

from test_daily_main_charge_windows import inputs
from test_supplemental_charge_commitment import charged

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.material_replanning import daily_grid_review_comparison


def test_shortfall_repair_not_compared_to_invalid_terminal_stock(tmp_path, monkeypatch):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states)))
    goal = store.load_supplemental_assignments()[0]
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == goal.next_assignment_id)
    state = next(s for s in snapshot.daily_charge_context.pv_comparison_states
                 if s.assignment_id == owner.assignment_id)
    comparison = replace(daily_grid_review_comparison(snapshot, state),
                         status="complete", actual_wh=100, central_wh=100)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.pv_surplus_trigger(snapshot=snapshot, assignment=owner,
        comparison=comparison, conversion_model=conversion)
    assert trigger is not None
    windows = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
        optimisation_trigger=trigger, conversion_model=conversion)
    assert any(w.supplemental_retirements for w in windows.windows)
    horizon = windows.windows[0].schedule.horizon_end
    incumbent = adapter.main_charge_incumbent(snapshot=snapshot, assignment=owner,
        conversion_model=conversion, horizon_end=horizon)

    # Producer boundary: the physics assessor reports a failed daily goal and
    # a lower ending inventory. Feasible alternatives must remain selectable.
    schedule = replace(incumbent.schedule, intervals=tuple(
        replace(i, intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY)
        if i.intent in (DailyStorageIntent.GRID_REQUIREMENT, DailyStorageIntent.NOM) else i
        for i in incumbent.schedule.intervals))
    physical = adapter._inputs(snapshot, horizon_end=horizon)
    projection = adapter._bridge_projection(snapshot, physical, schedule, conversion)
    incumbent = replace(incumbent, schedule=schedule, projection=projection,
        invalidity_reasons=("daily_main_goal_unreachable:" + owner.assignment_id,))
    portfolio = produce_main_charge_portfolio(snapshot=snapshot, windows=windows,
        tariffs=IndependentDailyTariffAdapter().build(snapshot, horizon_end=horizon),
        opportunity_ids=("supplemental-repair",), incumbent=incumbent)
    valid = [o for o in portfolio.outcome_set.outcomes if o.validity.value == 'valid']
    assert valid, [o.invalidity_reasons for o in portfolio.outcome_set.outcomes]
    different_stock = {
        s.candidate_id for s in portfolio.sources if s.window is not None
        and abs(s.window.projection.intervals[-1].storage_energy_at_end_wh
                - incumbent.projection.intervals[-1].storage_energy_at_end_wh) > 1e-6
    }
    assert different_stock
    assert different_stock <= {o.candidate_id for o in valid}
    reference = next(o for o in portfolio.outcome_set.outcomes
        if o.candidate_id == portfolio.incumbent_candidate_id)
    assert reference.validity.value == 'invalid'
    assert 'daily_main_goal_unreachable:' + owner.assignment_id in reference.invalidity_reasons
    assert all(v.unit == 'EUR/kWh-stored' for o in valid for v in o.objective_outcomes
        if v.objective.value == 'financial_result')
