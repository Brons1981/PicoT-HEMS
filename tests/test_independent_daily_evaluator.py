from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from test_independent_daily_reference_portfolio import _produce

from picot.domain.daily_reference_evaluation import (
    DailyReferenceEvaluationDirection,
    DailyReferenceExclusionReason,
)
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_evaluator import IndependentDailyEvaluator


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


def test_evaluator_excludes_grid_when_no_grid_path_is_proven_sufficient() -> None:
    candidates = _candidates()
    proven_grid = next(
        candidate
        for candidate in candidates.candidates
        if DailyStorageIntent.GRID_REQUIREMENT in candidate.intents_used
        and candidate.complete_across_scenarios
        and candidate.reserve_respected_across_scenarios
        and candidate.target_reached_across_scenarios
    )
    proven_pv = replace(
        proven_grid,
        candidate_id=f"{proven_grid.candidate_id}:pv-proof",
        intent_schedule_id=f"{proven_grid.intent_schedule_id}:pv-proof",
        intents_used=(DailyStorageIntent.NOM,),
    )
    candidates = replace(
        candidates,
        candidates=(proven_pv, *candidates.candidates),
    )

    result = IndependentDailyEvaluator().evaluate(candidates)

    no_grid_admitted = tuple(
        record
        for record, candidate in zip(result.records, candidates.candidates, strict=True)
        if DailyStorageIntent.GRID_REQUIREMENT not in candidate.intents_used
        and record.admissible
    )
    grid_records = tuple(
        record
        for record, candidate in zip(result.records, candidates.candidates, strict=True)
        if DailyStorageIntent.GRID_REQUIREMENT in candidate.intents_used
    )
    assert no_grid_admitted
    assert grid_records
    assert all(record.admissible is False for record in grid_records)
    assert all(
        DailyReferenceExclusionReason.GRID_NOT_REQUIRED_PV_RECOVERABLE
        in record.exclusion_reasons
        for record in grid_records
    )


def test_evaluator_allows_grid_comparison_only_after_no_grid_paths_fail() -> None:
    candidates = _candidates()
    changed = tuple(
        replace(
            candidate,
            scenario_outcomes=tuple(
                replace(
                    outcome,
                    target_reached_during_horizon=False,
                    target_reached_at=None,
                )
                for outcome in candidate.scenario_outcomes
            ),
            target_reached_across_scenarios=False,
        )
        if DailyStorageIntent.GRID_REQUIREMENT not in candidate.intents_used
        else candidate
        for candidate in candidates.candidates
    )

    result = IndependentDailyEvaluator().evaluate(
        replace(candidates, candidates=changed)
    )

    grid_records = tuple(
        record
        for record, candidate in zip(result.records, changed, strict=True)
        if DailyStorageIntent.GRID_REQUIREMENT in candidate.intents_used
    )
    assert grid_records
    assert any(record.admissible for record in grid_records)
    assert all(
        DailyReferenceExclusionReason.GRID_NOT_REQUIRED_PV_RECOVERABLE
        not in record.exclusion_reasons
        for record in grid_records
    )


def test_evaluator_does_not_import_current_pipeline_evaluation_or_commitment() -> None:
    from picot.planner import independent_daily_evaluator as module

    imported_names = set(vars(module))
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
