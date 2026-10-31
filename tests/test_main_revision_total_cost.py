"""Optional revisions must pay for the whole changed route, not just its refill."""

from dataclasses import replace

import pytest
from test_daily_main_charge_selection import portfolio_fixture

from picot.domain.evaluation import CandidateValidity
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import DailyMainIncumbentAssessment


def revision(incumbent_index, challenger_index, *, invalid=(), price_scale=1.0):
    snapshot, _, windows, tariffs, initial = portfolio_fixture()
    tariffs = replace(tariffs, intervals=tuple(replace(
        t, import_eur_per_kwh=t.import_eur_per_kwh * price_scale,
        export_eur_per_kwh=t.export_eur_per_kwh * price_scale,
    ) for t in tariffs.intervals))
    chosen = initial.sources[incumbent_index]
    single = produce_main_charge_portfolio(
        snapshot=snapshot, windows=replace(windows, windows=(chosen.window,)),
        tariffs=tariffs, opportunity_ids=("published-prices",),
    )
    selected = EvaluationEngine().evaluate(
        single.candidate_set, single.strategy, single.outcome_set,
        created_at=snapshot.captured_at,
    )
    plan = ExecutionPlanBuilder().build(
        selected, created_at=snapshot.captured_at, fallback_policy_id="nom-fallback",
    ).plans[0]
    w = chosen.window
    incumbent = DailyMainIncumbentAssessment(
        w.assignment_id, plan, w.family, w.schedule, w.main_segments,
        w.projection, w.target_storage_energy_wh, w.retained_main_segments,
        w.supplemental_assignments, invalid,
    )
    compared = produce_main_charge_portfolio(
        snapshot=snapshot,
        windows=replace(windows, windows=(initial.sources[challenger_index].window,)),
        tariffs=tariffs, opportunity_ids=("published-prices",), incumbent=incumbent,
        compare_complete_revision=True,
    )
    result = EvaluationEngine().evaluate(
        compared.candidate_set, compared.strategy, compared.outcome_set,
        created_at=snapshot.captured_at,
        incumbent_candidate_id=compared.incumbent_candidate_id,
        minimum_commitment_improvement_eur=0.01,
    )
    return compared, result


def test_cheaper_refill_but_more_expensive_total_route_retains_incumbent():
    compared, result = revision(7, 0)
    challenger, incumbent = compared.sources
    assert challenger.financial.acquisition_eur_per_stored_kwh < (
        incumbent.financial.acquisition_eur_per_stored_kwh)
    assert challenger.financial.cash_result_eur < incumbent.financial.cash_result_eur
    outcome = compared.outcome_set.outcomes[0]
    assert outcome.commitment_improvement_eur == pytest.approx(-0.20)
    assert outcome.objective_outcomes[0].unit == "EUR"
    assert result.record.winning_candidate_id == compared.incumbent_candidate_id


def test_true_total_saving_can_win_even_when_acquisition_rate_is_equal():
    compared, result = revision(0, 1)
    challenger, incumbent = compared.sources
    assert challenger.financial.acquisition_eur_per_stored_kwh == (
        incumbent.financial.acquisition_eur_per_stored_kwh)
    assert compared.outcome_set.outcomes[0].commitment_improvement_eur == pytest.approx(0.04)
    assert result.record.winning_candidate_id == challenger.candidate_id


def test_cheaper_route_cannot_spend_the_incumbents_terminal_inventory():
    compared, result = revision(20, 0)
    outcome = compared.outcome_set.outcomes[0]
    assert outcome.validity is CandidateValidity.INVALID
    assert "main_revision_terminal_inventory_not_equal" in outcome.invalidity_reasons
    assert outcome.commitment_improvement_eur is None
    assert result.record.winning_candidate_id == compared.incumbent_candidate_id


def test_invalid_incumbent_does_not_block_necessary_repair_on_terminal_stock():
    compared, result = revision(20, 0, invalid=("daily_main_goal_unreachable",))
    assert compared.outcome_set.outcomes[0].validity is CandidateValidity.VALID
    assert result.record.winning_candidate_id == compared.sources[0].candidate_id
    assert compared.outcome_set.outcomes[0].objective_outcomes[0].unit == "EUR/kWh-stored"


def test_subcent_total_saving_retains_the_existing_route():
    compared, result = revision(0, 1, price_scale=0.1)
    assert compared.outcome_set.outcomes[0].commitment_improvement_eur == pytest.approx(0.004)
    assert result.record.winning_candidate_id == compared.incumbent_candidate_id
    assert result.record.decisive_step == "commitment:minimum_improvement_incumbent_retained"
