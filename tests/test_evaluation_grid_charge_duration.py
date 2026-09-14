"""ADR-037.16: net charge duration only breaks a proven financial tie."""
from dataclasses import replace

import pytest
from test_evaluation_engine import BASE, _candidate_set, _outcome, _path, _strategy

from picot.domain.evaluation import CandidateOutcomeSet, CandidateValidity, TieBreakKind
from picot.domain.objectives import ObjectiveKind
from picot.planner.evaluation_engine import EvaluationEngine


def evaluate(a_duration=1800.0, b_duration=3600.0, *, incumbent="candidate-b",
             a_financial=1.0, b_financial=1.0, missing_financial=False, invalid_a=False,
             financial_margin=0.0, a_reserve=1000.0, b_reserve=1000.0, strategy=None):
    candidates = _candidate_set()
    a = replace(_outcome("candidate-a", a_financial, a_reserve),
                grid_charge_duration_seconds=a_duration)
    b = replace(_outcome("candidate-b", b_financial, b_reserve),
                grid_charge_duration_seconds=b_duration)
    if invalid_a:
        a = replace(
            a, validity=CandidateValidity.INVALID, invalidity_reasons=("reserve_shortfall",),
        )
    if missing_financial:
        a = replace(a, objective_outcomes=tuple(
            x for x in a.objective_outcomes if x.objective != ObjectiveKind.FINANCIAL_RESULT))
    outcomes = CandidateOutcomeSet(candidates.snapshot_id, candidates.strategy_version,
                                  EvaluationEngine.candidate_set_reference(candidates), (a, b))
    return EvaluationEngine().evaluate(candidates, strategy or _strategy(), outcomes,
                                       created_at=BASE, incumbent_candidate_id=incumbent,
                                       financial_equivalence_margin=financial_margin)


def test_shorter_grid_duration_beats_equivalent_incumbent():
    result = evaluate()
    assert result.record.winning_candidate_id == "candidate-a"
    assert result.record.decisive_step == "tie_break:grid_charge_duration"
    record = result.record.tie_breaks[0]
    assert record.kind == TieBreakKind.GRID_CHARGE_DURATION
    assert record.available and record.decisive
    assert [v.value for v in record.values] == [1800.0, 3600.0]


def test_equal_grid_duration_keeps_incumbent_and_comparison_evidence():
    result = evaluate(1800.0, 1800.0)
    assert result.record.winning_candidate_id == "candidate-b"
    assert [r.kind for r in result.record.tie_breaks] == [
        TieBreakKind.GRID_CHARGE_DURATION, TieBreakKind.INCUMBENT_COMMITMENT,
    ]
    assert not result.record.tie_breaks[0].decisive


def test_equal_duration_preserves_record_before_general_ties():
    result = evaluate(1800.0, 1800.0, incumbent=None)
    assert result.record.tie_breaks[0].kind == TieBreakKind.GRID_CHARGE_DURATION
    assert result.record.tie_breaks[-1].kind == TieBreakKind.CANDIDATE_IDENTIFIER


@pytest.mark.parametrize("kwargs", (
    {"a_financial": 0.9}, {"missing_financial": True}, {"invalid_a": True},
    {"a_duration": None}, {"b_duration": None},
))
def test_shorter_duration_never_overrides_price_validity_or_missing_evidence(kwargs):
    assert evaluate(**kwargs).record.winning_candidate_id == "candidate-b"


@pytest.mark.parametrize("value", (-1.0, float("inf"), float("-inf"), float("nan")))
def test_duration_requires_finite_nonnegative_seconds(value):
    with pytest.raises(ValueError, match="Grid charge duration"):
        replace(_outcome("candidate-a", 1.0, 1000.0), grid_charge_duration_seconds=value)


def test_zero_grid_charge_is_valid_and_preferred():
    assert evaluate(0.0, 60.0).record.winning_candidate_id == "candidate-a"


def test_margin_does_not_invent_exact_financial_equality_for_duration():
    result = evaluate(a_financial=0.99, financial_margin=0.05)
    assert result.record.winning_candidate_id == "candidate-b"
    assert result.record.tie_breaks[0].kind == TieBreakKind.GRID_CHARGE_DURATION
    assert not result.record.tie_breaks[0].available


def test_duration_can_remove_incumbent_then_continue_with_general_ties():
    candidates = _candidate_set()
    candidate_c, path_c = _path("path-c", "candidate-c")
    candidates = replace(candidates, candidates=(*candidates.candidates, candidate_c),
                         energy_paths=(*candidates.energy_paths, path_c))
    outcomes = CandidateOutcomeSet(
        candidates.snapshot_id, candidates.strategy_version,
        EvaluationEngine.candidate_set_reference(candidates),
        tuple(replace(_outcome(identifier, 1.0, 1000.0), grid_charge_duration_seconds=duration)
              for identifier, duration in (("candidate-a", 60), ("candidate-b", 120),
                                           ("candidate-c", 60))),
    )
    result = EvaluationEngine().evaluate(candidates, _strategy(), outcomes, created_at=BASE,
                                         incumbent_candidate_id="candidate-b")
    assert result.record.winning_candidate_id == "candidate-a"
    assert result.record.tie_breaks[0].retained_candidate_ids == ("candidate-a", "candidate-c")
    assert result.record.tie_breaks[0].kind == TieBreakKind.GRID_CHARGE_DURATION
    assert result.record.tie_breaks[-1].kind == TieBreakKind.CANDIDATE_IDENTIFIER


def test_equal_cost_shorter_valid_grid_charge_wins_without_maximizing_reserve():
    result = evaluate(a_reserve=1660.0, b_reserve=1760.0)
    assert result.record.winning_candidate_id == "candidate-a"
    assert result.record.decisive_step == "tie_break:grid_charge_duration"
    assert [r.objective for r in result.record.objective_comparisons] == [
        ObjectiveKind.FINANCIAL_RESULT,
    ]


def test_shorter_infeasible_path_never_wins_equal_cost_comparison():
    result = evaluate(a_reserve=1660.0, b_reserve=1760.0, invalid_a=True)
    assert result.record.winning_candidate_id == "candidate-b"
    assert result.record.invalid_candidates[0].candidate_id == "candidate-a"


def test_higher_priority_reserve_objective_still_precedes_financial_duration():
    from picot.domain.objectives import ObjectiveWeight

    strategy = _strategy()
    strategy = replace(strategy, objectives=tuple(
        replace(objective, weight=ObjectiveWeight(900))
        if objective.objective == ObjectiveKind.RESERVE_AVAILABILITY else objective
        for objective in strategy.objectives
    ))
    result = evaluate(a_reserve=1660.0, b_reserve=1760.0, strategy=strategy)
    assert result.record.winning_candidate_id == "candidate-b"
    assert result.record.decisive_step == "objective:reserve_availability"


def test_equal_duration_continues_to_lower_priority_reserve_objective():
    result = evaluate(60.0, 60.0, a_reserve=1660.0, b_reserve=1760.0)
    assert result.record.winning_candidate_id == "candidate-b"
    assert result.record.decisive_step == "objective:reserve_availability"
    assert result.record.tie_breaks[0].kind == TieBreakKind.GRID_CHARGE_DURATION
    assert not result.record.tie_breaks[0].decisive
