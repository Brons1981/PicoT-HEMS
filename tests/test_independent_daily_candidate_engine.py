from __future__ import annotations

from dataclasses import replace

import pytest
from test_independent_daily_financial_settlement import _tariffs
from test_independent_daily_reference_portfolio import _produce as _produce_portfolio
from test_independent_daily_simulator import _simulate

from picot.domain.daily_reference_candidate import DailyReferenceCandidateFamily
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import PVScenario
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_reference_run import (
    IndependentDailyReferenceRunProducer,
)


def _run():
    return IndependentDailyReferenceRunProducer().produce(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )


def test_engine_builds_only_the_physically_proven_nom_candidate() -> None:
    run = _run()
    result = IndependentDailyCandidateEngine().build(run)

    assert result.source_run_id == run.run_id
    assert result.observer_only is True
    assert result.ranking_permitted is False
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.family is DailyReferenceCandidateFamily.NOM_FULL_HORIZON
    assert candidate.complete_across_scenarios is True
    assert candidate.selection_eligible is False
    assert {item.scenario for item in candidate.scenario_outcomes} == set(PVScenario)


def test_candidate_worst_case_and_confidence_come_from_all_scenarios() -> None:
    candidate = IndependentDailyCandidateEngine().build(_run()).candidates[0]

    assert candidate.worst_case_financial_result_eur == min(
        item.net_financial_result_eur for item in candidate.scenario_outcomes
    )
    assert candidate.minimum_confidence == min(
        item.confidence for item in candidate.scenario_outcomes
    )


def test_engine_rejects_run_not_closed_for_candidate_input() -> None:
    incomplete = replace(_run())
    object.__setattr__(incomplete, "candidate_input_complete", False)

    with pytest.raises(ValueError, match="requires a complete daily run"):
        IndependentDailyCandidateEngine().build(incomplete)


def test_engine_builds_one_unranked_candidate_per_portfolio_strategy() -> None:
    portfolio = _produce_portfolio()
    result = IndependentDailyCandidateEngine().build_portfolio(portfolio)

    assert result.source_portfolio_id == portfolio.portfolio_id
    assert result.ranking_permitted is False
    assert len(result.candidates) == len(portfolio.strategy_results)
    assert {item.family for item in result.candidates} == {
        DailyReferenceCandidateFamily.HOUSEHOLD_SUPPORT_ONLY,
        DailyReferenceCandidateFamily.NOM,
        DailyReferenceCandidateFamily.STANDBY,
        DailyReferenceCandidateFamily.GRID_REQUIREMENT,
        DailyReferenceCandidateFamily.STORAGE_EXPORT,
    }
    assert all(item.selection_eligible is False for item in result.candidates)
    assert len({item.intent_schedule_id for item in result.candidates}) == len(
        result.candidates
    )


def test_engine_uses_relevant_average_tariff_without_fixed_margin() -> None:
    result = IndependentDailyCandidateEngine().build_portfolio(_produce_portfolio())
    nom = next(
        item
        for item in result.candidates
        if item.intents_used == (DailyStorageIntent.NOM,)
    )
    grid = next(
        item
        for item in result.candidates
        if item.intents_used == (DailyStorageIntent.GRID_REQUIREMENT,)
    )

    assert nom.average_charge_window_price_eur_per_kwh == pytest.approx(0.10)
    assert grid.average_charge_window_price_eur_per_kwh == pytest.approx(0.30)
    assert nom.charge_window_confidence is not None
    assert grid.charge_window_confidence is not None


def test_engine_does_not_import_current_candidate_or_evaluation_modules() -> None:
    from picot.planner import independent_daily_candidate_engine as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
