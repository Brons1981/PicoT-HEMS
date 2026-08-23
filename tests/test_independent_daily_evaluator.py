from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from picot.domain.daily_reference_evaluation import (
    DailyReferenceEvaluationDirection,
    DailyReferenceExclusionReason,
)
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_evaluator import IndependentDailyEvaluator
from test_independent_daily_reference_portfolio import _produce


def _candidates():
    return IndependentDailyCandidateEngine().build_portfolio(_produce())


def test_evaluator_applies_physical_gates_before_financial_comparison() -> None:
    result = IndependentDailyEvaluator().evaluate(_candidates())

    assert result.direction is DailyReferenceEvaluationDirection.HIGHER_IS_BETTER
    assert result.observer_only is True
    assert result.selection_permitted is False
    assert result.commitment_permitted is False
    assert result.best_candidate_ids
    assert all(
        record.admissible
        for record in result.records
        if record.candidate_id in result.best_candidate_ids
    )
    assert all(
        record.worst_case_financial_result_eur
        == max(
            item.worst_case_financial_result_eur
            for item in result.records
            if item.admissible
        )
        for record in result.records
        if record.best_observation
    )


def test_evaluator_explains_excluded_candidate_instead_of_dropping_it() -> None:
    candidates = _candidates()
    changed = replace(
        candidates.candidates[0],
        scenario_outcomes=tuple(
            replace(
                item,
                target_reached_during_horizon=False,
                target_reached_at=None,
            )
            for item in candidates.candidates[0].scenario_outcomes
        ),
        target_reached_across_scenarios=False,
    )
    candidate_set = replace(
        candidates,
        candidates=(changed, *candidates.candidates[1:]),
    )

    result = IndependentDailyEvaluator().evaluate(candidate_set)
    record = next(
        item for item in result.records if item.candidate_id == changed.candidate_id
    )

    assert record.admissible is False
    assert record.exclusion_reasons == (
        DailyReferenceExclusionReason.TARGET_NOT_REACHED,
    )
    assert record.best_observation is False


def test_evaluator_allows_discharge_after_target_when_reserve_is_respected() -> None:
    candidates = _candidates()
    original = candidates.candidates[3]
    changed = replace(
        original,
        scenario_outcomes=tuple(
            replace(item, target_held_at_horizon_end=False)
            for item in original.scenario_outcomes
        ),
        target_held_across_scenarios=False,
    )
    candidate_set = replace(candidates, candidates=(changed,))

    record = IndependentDailyEvaluator().evaluate(candidate_set).records[0]

    assert changed.target_reached_across_scenarios is True
    assert changed.reserve_respected_across_scenarios is True
    assert record.admissible is True
    assert record.exclusion_reasons == ()


def test_evaluator_preserves_exact_ties_without_hidden_tie_break() -> None:
    candidates = _candidates()
    first = candidates.candidates[0]
    second = candidates.candidates[1]
    tied_result = max(
        first.worst_case_financial_result_eur,
        second.worst_case_financial_result_eur,
    )
    first = replace(
        first,
        scenario_outcomes=tuple(
            replace(
                item,
                net_financial_result_eur=tied_result,
                target_reached_during_horizon=True,
                target_reached_at=datetime(2026, 8, 23, tzinfo=UTC),
                target_held_at_horizon_end=True,
            )
            for item in first.scenario_outcomes
        ),
        worst_case_financial_result_eur=tied_result,
        target_reached_across_scenarios=True,
        target_held_across_scenarios=True,
    )
    second = replace(
        second,
        scenario_outcomes=tuple(
            replace(
                item,
                net_financial_result_eur=tied_result,
                target_reached_during_horizon=True,
                target_reached_at=datetime(2026, 8, 23, tzinfo=UTC),
                target_held_at_horizon_end=True,
            )
            for item in second.scenario_outcomes
        ),
        worst_case_financial_result_eur=tied_result,
        target_reached_across_scenarios=True,
        target_held_across_scenarios=True,
    )
    candidate_set = replace(
        candidates,
        candidates=(first, second),
    )

    result = IndependentDailyEvaluator().evaluate(candidate_set)

    assert result.best_candidate_ids == (first.candidate_id, second.candidate_id)


def test_evaluator_does_not_import_current_pipeline_evaluation_or_commitment() -> None:
    from picot.planner import independent_daily_evaluator as module

    imported_names = set(vars(module))
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
