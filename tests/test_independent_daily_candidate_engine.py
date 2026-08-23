from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_candidate import DailyReferenceCandidateFamily
from picot.domain.daily_reference_simulation import PVScenario
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_reference_run import (
    IndependentDailyReferenceRunProducer,
)
from test_independent_daily_financial_settlement import _tariffs
from test_independent_daily_simulator import _simulate


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


def test_engine_does_not_import_current_candidate_or_evaluation_modules() -> None:
    from picot.planner import independent_daily_candidate_engine as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
