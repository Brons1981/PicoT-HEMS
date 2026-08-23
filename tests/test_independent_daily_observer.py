from __future__ import annotations

from dataclasses import replace

import pytest

from picot.planner.independent_daily_observer import IndependentDailyObserver
from test_independent_daily_reference_portfolio import _produce


def test_observer_closes_portfolio_candidates_and_evaluation_into_one_result() -> None:
    portfolio = _produce()
    result = IndependentDailyObserver().observe(portfolio)

    assert result.snapshot_id == portfolio.snapshot_id
    assert result.portfolio is portfolio
    assert result.candidate_set.source_portfolio_id == portfolio.portfolio_id
    assert (
        result.evaluation.source_candidate_set_id
        == result.candidate_set.candidate_set_id
    )
    assert result.best_observation_ids == result.evaluation.best_candidate_ids
    assert result.observer_only is True
    assert result.selection_permitted is False
    assert result.commitment_permitted is False


def test_observer_result_blocks_candidate_lineage_from_another_portfolio() -> None:
    result = IndependentDailyObserver().observe(_produce())
    changed_candidates = replace(
        result.candidate_set,
        source_portfolio_id="another-portfolio",
    )

    with pytest.raises(ValueError, match="candidate lineage must match portfolio"):
        replace(result, candidate_set=changed_candidates)


def test_observer_result_blocks_evaluation_records_not_matching_candidates() -> None:
    result = IndependentDailyObserver().observe(_produce())
    changed_evaluation = replace(
        result.evaluation,
        records=tuple(reversed(result.evaluation.records)),
        best_candidate_ids=tuple(
            item.candidate_id
            for item in reversed(result.evaluation.records)
            if item.best_observation
        ),
    )

    with pytest.raises(ValueError, match="candidate and evaluation records must match"):
        replace(result, evaluation=changed_evaluation)


def test_observer_does_not_import_live_pipeline_or_commitment() -> None:
    from picot.planner import independent_daily_observer as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
