"""Daily user capacity is an upper bound, not a mandatory export quantity."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_market_complete_recovery_candidates import complete_recovery_fixture
from test_market_price_windows import alternatives
from test_market_route_admission import inputs

from picot.domain.market_user_rule import MarketUserRule
from picot.domain.solar_export_bonus import SolarExportBonusContext, SolarExportBonusPolicy
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.market_export_windows import export_volume_targets
from picot.planner.market_route_admission import assess_market_route
from picot.v2.market_rule_planning import _quantity_aware_spread, market_rule_portfolio


def test_zero_user_capacity_is_a_valid_disabled_instruction():
    rule = MarketUserRule("trade", 1, 0, 0.2)
    assert alternatives(rule=rule) == ()


@pytest.mark.parametrize("maximum", [0, 816, 2040, 3060])
def test_volume_search_is_bounded_deterministic_and_includes_exact_maximum(maximum):
    volumes = export_volume_targets(maximum)
    assert volumes == export_volume_targets(maximum)
    assert len(volumes) == (5 if maximum else 0)
    if maximum:
        assert volumes[-1] == maximum
        assert all(0 < volume <= maximum for volume in volumes)


def test_selected_volume_cannot_exceed_frozen_daily_cap():
    args = inputs(pv=True)
    args["assignment"] = replace(
        args["assignment"], rule=replace(args["assignment"].rule, capacity_fraction=0.01)
    )
    with pytest.raises(ValueError, match="daily capacity maximum"):
        assess_market_route(**args)


@pytest.mark.parametrize("prior_pv_kwh,expected_price", [(0, 0.63), (0.6, 0.6)])
@pytest.mark.parametrize("excluded_grid_wh", [0, 200])
def test_spread_cannot_spend_bonus_allowance_already_used_by_pv(
    prior_pv_kwh, expected_price, excluded_grid_wh,
):
    args = inputs(pv=True)
    projection, spread, tariffs = args["proposed"], args["spread"], args["tariffs"]
    first = projection.intervals[0]
    projection = replace(projection, intervals=(replace(
        first, household_demand_wh=first.household_demand_wh + excluded_grid_wh,
        grid_to_household_wh=excluded_grid_wh, battery_excluded_demand_wh=excluded_grid_wh,
    ), *projection.intervals[1:]))
    at = projection.intervals[0].starts_at
    policy = SolarExportBonusPolicy(True, at - timedelta(days=1), 51.6, 4.6,
                                   7499.4, at - timedelta(hours=1))
    context = SolarExportBonusContext(policy, at, ((2026, 0.6),), ("annual-meter",))
    tariffs = replace(tariffs, solar_export_bonus=context, intervals=tuple(
        replace(i, solar_bonus_eur_per_kwh=0.06) for i in tariffs.intervals
    ))
    spread = replace(spread, export_window=replace(spread.export_window, parts=tuple(
        replace(p, price_eur_per_kwh=0.66) for p in spread.export_window.parts
    )))
    if prior_pv_kwh:
        prior = replace(projection.intervals[0], starts_at=at - timedelta(hours=1), ends_at=at,
                        pv_to_grid_wh=prior_pv_kwh * 1000, storage_to_grid_output_wh=0,
                        grid_to_household_wh=0, grid_to_storage_input_wh=0,
                        usable_pv_wh=prior_pv_kwh * 1000, household_demand_wh=0,
                        storage_to_household_output_wh=0, storage_discharge_loss_wh=0,
                        battery_excluded_demand_wh=0,
                        storage_energy_at_end_wh=projection.intervals[0].storage_energy_at_start_wh)
        timeline = projection.basis_timeline
        pv = replace(timeline.intervals[0], starts_at=prior.starts_at, ends_at=prior.ends_at,
                     energy_wh=prior_pv_kwh * 1000)
        projection = replace(projection, intervals=(prior, *projection.intervals),
                             basis_timeline=replace(timeline, horizon_start=prior.starts_at,
                                                    intervals=(pv, *timeline.intervals)))
        price = replace(tariffs.intervals[0], starts_at=prior.starts_at, ends_at=prior.ends_at)
        tariffs = replace(tariffs, horizon_start=prior.starts_at,
                          intervals=(price, *tariffs.intervals))
    corrected = _quantity_aware_spread(spread, projection, tariffs)
    assert corrected.export_window.average_eur_per_kwh == pytest.approx(expected_price)


def test_smaller_complete_route_can_be_admitted_below_daily_cap():
    args = inputs(pv=True)
    args["assignment"] = replace(
        args["assignment"], rule=replace(args["assignment"].rule, capacity_fraction=0.5)
    )
    assert args["spread"].battery_energy_wh < args["assignment"].battery_energy_wh
    result = assess_market_route(**args)
    assert result.status == "admissible", result.reason


def test_price_reference_uses_selected_smaller_energy_not_maximum():
    evidence = alternatives(battery_energy_wh=816)
    assert evidence
    assert all(e.battery_energy_wh == 816 for e in evidence)
    assert all(e.reference_window.grid_energy_wh == pytest.approx(1020) for e in evidence)
    assert all(e.export_window.grid_energy_wh == pytest.approx(734.4) for e in evidence)


def test_small_profitable_trade_survives_unprofitable_full_cap(tmp_path, monkeypatch):
    snapshot, plan, assignment, _ = complete_recovery_fixture(tmp_path, monkeypatch)
    rule = replace(assignment.rule, capacity_fraction=0.25, minimum_spread_eur_per_kwh=0.4)
    snapshot = replace(snapshot, market_user_rule=rule, price_points=tuple(
        replace(p, value_eur_per_kwh=0.1)
        if p.starts_at.hour == 15 and p.starts_at.minute != 0 else p
        for p in snapshot.price_points
    ))
    assignment = replace(assignment, rule=rule)
    from test_daily_main_charge_windows import inputs as physical_inputs

    market = market_rule_portfolio(
        snapshot=snapshot, plan=plan, assignment=assignment,
        conversion=physical_inputs()["conversion_model"], opportunity_ids=(),
    )
    assert market.evidence, market.reasons
    assert all(e.spread.battery_energy_wh < assignment.battery_energy_wh for e in market.evidence)
    assert any(e.spread.battery_energy_wh == pytest.approx(816) for e in market.evidence)
    selected = EvaluationEngine().evaluate(
        market.comparable.candidate_set, market.comparable.strategy,
        market.comparable.outcome_set, created_at=snapshot.captured_at,
    )
    winner = next(e for e in market.evidence
                  if e.candidate_id == selected.record.winning_candidate_id)
    assert winner.admission.incremental_net_profit_eur == max(
        e.admission.incremental_net_profit_eur for e in market.evidence
    )
    assert "market_volume_search_steps:5" in next(
        c.assumptions for c in market.comparable.candidate_set.candidates
        if c.candidate_id == winner.candidate_id
    )


def test_waiting_assignment_respects_lower_current_cap_without_replenishing(tmp_path, monkeypatch):
    snapshot, plan, assignment, _ = complete_recovery_fixture(tmp_path, monkeypatch)
    from test_daily_main_charge_windows import inputs as physical_inputs

    original = assignment
    lowered = replace(snapshot.market_user_rule, capacity_fraction=0.05)
    market = market_rule_portfolio(
        snapshot=replace(snapshot, market_user_rule=lowered), plan=plan, assignment=assignment,
        conversion=physical_inputs()["conversion_model"], opportunity_ids=(),
    )
    assert market.evidence, market.reasons
    assert all(e.spread.battery_energy_wh <= 408 + 1e-6 for e in market.evidence)
    assert assignment == original
    with pytest.raises(ValueError, match="market_disabled_by_zero_capacity"):
        market_rule_portfolio(
            snapshot=replace(snapshot, market_user_rule=replace(lowered, capacity_fraction=0)),
            plan=plan, assignment=assignment,
            conversion=physical_inputs()["conversion_model"], opportunity_ids=(),
        )
