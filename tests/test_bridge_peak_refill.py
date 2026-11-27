from dataclasses import replace

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.evaluation import CandidateValidity
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter


@pytest.mark.parametrize(("soc", "optional"), [(0.65, False), (1.0, True)])
def test_expensive_standby_can_be_replaced_by_support_and_later_refill(tmp_path, soc, optional):
    _, snapshot, plan = scenario(tmp_path, soc=soc)
    segments = tuple(
        replace(
            segment, primitive=ExecutionPrimitive.STANDBY, requested_power_w=None,
            purpose="retained-route",
        ) if segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER else segment
        for segment in plan.segments
    )
    context = replace(
        snapshot.daily_charge_context,
        main_plans=(replace(plan, segments=segments),),
        market_plan_bindings=(),
        market_execution_progress=(),
    )
    snapshot = replace(snapshot, daily_charge_context=context, market_user_rule=None)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    assert trigger is not None
    assert trigger.price_peak_review is optional
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion,
    )
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.windows[0].schedule.horizon_end,
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs,
        opportunity_ids=(), peak_refill_wear_eur_per_kwh=0.02,
    )
    valid = {outcome.candidate_id for outcome in portfolio.outcome_set.outcomes
             if outcome.validity is CandidateValidity.VALID}
    alternatives = [
        source for source in portfolio.sources
        if source.peak_refill_comparison is not None and source.candidate_id in valid
    ]
    assert alternatives, [
        (source.peak_refill_comparison, outcome.invalidity_reasons)
        for source, outcome in zip(portfolio.sources, portfolio.outcome_set.outcomes, strict=True)
        if source.peak_refill_comparison is not None
    ]
    for source in alternatives:
        assert source.peak_refill_comparison["avoided_grid_kwh"] > 0
        assert source.peak_refill_comparison["extra_refill_kwh"] > 0
        assert source.peak_refill_comparison["saving_eur"] > 0.01
        assert source.window.main_segments
        assert source.window.projection.intervals[-1].storage_energy_at_end_wh == (
            windows.peak_refill_reference.intervals[-1].storage_energy_at_end_wh
        )
