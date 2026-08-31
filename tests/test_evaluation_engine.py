from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.energy_path import EnergyPath
from picot.domain.evaluation import (
    CandidateOutcome,
    CandidateOutcomeSet,
    CandidateValidity,
    ComparisonDirection,
    EvaluationOutcomeStatus,
    ObjectiveOutcome,
    TieBreakKind,
)
from picot.domain.objectives import (
    ObjectiveKind,
    ObjectiveWeight,
    OptimisationProfile,
    PlannerStrategy,
    WeightedObjective,
)
from picot.planner.evaluation_engine import EvaluationEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _path(path_id: str, candidate_id: str) -> tuple[Candidate, EnergyPath]:
    family = (
        CandidateFamily.RESERVE_FIRST
        if candidate_id == "candidate-a"
        else CandidateFamily.PV_FIRST
    )
    path = EnergyPath(
        path_id=path_id,
        snapshot_id="snapshot-1",
        family=family,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=36),
        segments=(),
        projected_states=(),
        opportunity_ids=(),
        constraint_ids=(),
        capability_ids=(),
        strategy_version=2,
        mapping_version=3,
        assumptions=(),
        confidence=0.9,
    )
    candidate = Candidate(
        candidate_id=candidate_id,
        snapshot_id="snapshot-1",
        family=family,
        energy_path_id=path_id,
        opportunity_ids=(),
        constraint_ids=(),
        strategy_version=2,
        capability_ids=(),
        assumptions=(),
        confidence=0.9,
    )
    return candidate, path


def _candidate_set() -> CandidateSet:
    candidate_a, path_a = _path("path-a", "candidate-a")
    candidate_b, path_b = _path("path-b", "candidate-b")
    return CandidateSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidates=(candidate_a, candidate_b),
        energy_paths=(path_a, path_b),
        exclusions=(),
    )


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=2,
        source_profile_version=1,
        mapping_version="objective-map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(
            WeightedObjective(ObjectiveKind.FINANCIAL_RESULT, ObjectiveWeight(800)),
            WeightedObjective(ObjectiveKind.RESERVE_AVAILABILITY, ObjectiveWeight(500)),
        ),
    )


def _outcome(candidate_id: str, financial: float, reserve: float) -> CandidateOutcome:
    return CandidateOutcome(
        candidate_id=candidate_id,
        objective_outcomes=(
            ObjectiveOutcome(
                objective=ObjectiveKind.FINANCIAL_RESULT,
                value=financial,
                direction=ComparisonDirection.HIGHER_IS_BETTER,
                unit="EUR",
                confidence=0.95,
            ),
            ObjectiveOutcome(
                objective=ObjectiveKind.RESERVE_AVAILABILITY,
                value=reserve,
                direction=ComparisonDirection.HIGHER_IS_BETTER,
                unit="WH",
                confidence=0.9,
            ),
        ),
        confidence=0.9,
        recoverability=0.8,
        execution_complexity=1,
        expected_switching_count=1,
        complexity_version="v1",
        validity=CandidateValidity.VALID,
    )


def _outcome_set(candidate_set: CandidateSet) -> CandidateOutcomeSet:
    engine = EvaluationEngine()
    return CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=engine.candidate_set_reference(candidate_set),
        outcomes=(
            _outcome("candidate-a", financial=1.0, reserve=3000.0),
            _outcome("candidate-b", financial=2.0, reserve=1000.0),
        ),
    )


def test_evaluation_selects_candidate_by_highest_weighted_objective() -> None:
    candidate_set = _candidate_set()
    result = EvaluationEngine().evaluate(
        candidate_set,
        _strategy(),
        _outcome_set(candidate_set),
        created_at=BASE,
    )

    assert result.status is EvaluationOutcomeStatus.WINNER_SELECTED
    assert result.winning_candidate is not None
    assert result.winning_candidate.candidate_id == "candidate-b"
    assert result.winning_energy_path is not None
    assert result.winning_energy_path.path_id == "path-b"
    assert result.record.decisive_step == "objective:financial_result"


def test_evaluation_uses_candidate_identifier_as_final_tie_break() -> None:
    candidate_set = _candidate_set()
    reference = EvaluationEngine().candidate_set_reference(candidate_set)
    equal = CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=reference,
        outcomes=(
            _outcome("candidate-a", financial=1.0, reserve=1000.0),
            _outcome("candidate-b", financial=1.0, reserve=1000.0),
        ),
    )

    result = EvaluationEngine().evaluate(candidate_set, _strategy(), equal, created_at=BASE)

    assert result.winning_candidate is not None
    assert result.winning_candidate.candidate_id == "candidate-a"
    assert result.record.tie_breaks[-1].kind is TieBreakKind.CANDIDATE_IDENTIFIER


def test_evaluation_returns_no_winner_when_all_candidates_invalid() -> None:
    candidate_set = _candidate_set()
    reference = EvaluationEngine().candidate_set_reference(candidate_set)
    invalid = CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=reference,
        outcomes=tuple(
            CandidateOutcome(
                candidate_id=candidate_id,
                objective_outcomes=(),
                confidence=0.8,
                recoverability=None,
                execution_complexity=0,
                expected_switching_count=None,
                complexity_version="v1",
                validity=CandidateValidity.INVALID,
                invalidity_reasons=("Hard feasibility failure.",),
            )
            for candidate_id in ("candidate-a", "candidate-b")
        ),
    )

    result = EvaluationEngine().evaluate(candidate_set, _strategy(), invalid, created_at=BASE)

    assert result.status is EvaluationOutcomeStatus.NO_VALID_CANDIDATE
    assert result.winning_candidate is None
    assert len(result.record.invalid_candidates) == 2


def test_evaluation_rejects_mismatched_candidate_outcomes() -> None:
    candidate_set = _candidate_set()
    mismatched = CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=EvaluationEngine().candidate_set_reference(candidate_set),
        outcomes=(_outcome("candidate-a", financial=1.0, reserve=1000.0),),
    )

    with pytest.raises(ValueError, match="must match exactly"):
        EvaluationEngine().evaluate(candidate_set, _strategy(), mismatched, created_at=BASE)


def test_financial_equivalence_retains_explicit_incumbent() -> None:
    candidate_set = _candidate_set()
    reference = EvaluationEngine().candidate_set_reference(candidate_set)
    close = CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=reference,
        outcomes=(
            _outcome("candidate-a", financial=1.04, reserve=1000.0),
            _outcome("candidate-b", financial=1.00, reserve=1000.0),
        ),
    )

    result = EvaluationEngine().evaluate(
        candidate_set,
        _strategy(),
        close,
        created_at=BASE,
        incumbent_candidate_id="candidate-b",
        financial_equivalence_margin=0.05,
    )

    assert result.winning_candidate is not None
    assert result.winning_candidate.candidate_id == "candidate-b"
    assert result.record.decisive_step == "commitment:equivalent_incumbent_retained"
    assert result.record.objective_comparisons[0].equivalence_margin == 0.05
    assert result.record.tie_breaks[0].kind is TieBreakKind.INCUMBENT_COMMITMENT


def test_financial_improvement_beyond_margin_replaces_incumbent() -> None:
    candidate_set = _candidate_set()
    reference = EvaluationEngine().candidate_set_reference(candidate_set)
    improved = CandidateOutcomeSet(
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference=reference,
        outcomes=(
            _outcome("candidate-a", financial=1.051, reserve=1000.0),
            _outcome("candidate-b", financial=1.00, reserve=1000.0),
        ),
    )

    result = EvaluationEngine().evaluate(
        candidate_set,
        _strategy(),
        improved,
        created_at=BASE,
        incumbent_candidate_id="candidate-b",
        financial_equivalence_margin=0.05,
    )

    assert result.winning_candidate is not None
    assert result.winning_candidate.candidate_id == "candidate-a"
    assert result.record.decisive_step == "objective:financial_result"
