"""A complete supplemental revision compares cash on equal terminal stock."""

from dataclasses import replace

from test_daily_main_charge_windows import inputs
from test_supplemental_charge_commitment import charged

from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.material_replanning import daily_grid_review_comparison


def test_retirement_costs_include_whole_route_in_same_units(tmp_path, monkeypatch):
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
    portfolio = produce_main_charge_portfolio(snapshot=snapshot, windows=windows,
        tariffs=IndependentDailyTariffAdapter().build(snapshot, horizon_end=horizon),
        opportunity_ids=("supplemental-review",), incumbent=incumbent)
    financial = [v for o in portfolio.outcome_set.outcomes for v in o.objective_outcomes
                 if v.objective.value == "financial_result"]
    assert financial and all(v.unit == "EUR" for v in financial)
    assert any(o.validity.value == "valid" for o in portfolio.outcome_set.outcomes)
    for source in portfolio.sources:
        if source.window is None:
            continue
        outcome = next(o for o in portfolio.outcome_set.outcomes
                       if o.candidate_id == source.candidate_id)
        if outcome.validity.value == "valid":
            assert abs(source.window.projection.intervals[-1].storage_energy_at_end_wh
                       - incumbent.projection.intervals[-1].storage_energy_at_end_wh) < 1e-6
