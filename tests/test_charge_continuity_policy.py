"""Committed charging and explicitly bounded optional replacements."""

from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_pv_route_optimisation import observed, source_with_later_cheap_window
from test_evaluation_engine import BASE, _candidate_set, _outcome_set, _strategy

from picot.domain.evaluation import CandidateValidity
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_running_grid_block_is_protected_without_extra_household_load(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    grid = next(s for s in first.execution_plan_set.plans[0].segments
                if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    minutes = (grid.starts_at - source.captured_at).total_seconds() / 60 + 1
    snapshot = recover(observed(source, soc=0.90, minutes=minutes))
    owner = store.load_daily_assignments()[0]
    assert IndependentDailyReferenceAdapter._protected_grid_end(snapshot, owner) == grid.ends_at
    full = replace(snapshot, current_storage_states=tuple(
        replace(s, current_soc=1.0) for s in snapshot.current_storage_states))
    assert IndependentDailyReferenceAdapter._protected_grid_end(full, owner) is None


@pytest.mark.parametrize("benefit,winner", [
    (0.0003, "candidate-a"), (0.0036, "candidate-a"),
    (0.0099, "candidate-a"), (0.01, "candidate-b"), (0.02, "candidate-b"),
])
def test_optional_replacement_requires_one_cent(benefit, winner):
    candidates = _candidate_set()
    outcomes = _outcome_set(candidates)
    outcomes = replace(outcomes, outcomes=tuple(replace(
        o, commitment_improvement_eur=0.0 if o.candidate_id == "candidate-a" else benefit,
        grid_charge_duration_seconds=3600 if o.candidate_id == "candidate-a" else 0,
    ) for o in outcomes.outcomes))
    result = EvaluationEngine().evaluate(
        candidates, _strategy(), outcomes, created_at=BASE,
        incumbent_candidate_id="candidate-a", minimum_commitment_improvement_eur=0.01,
    )
    assert result.record.winning_candidate_id == winner
    assert result.record.tie_breaks[0].kind.value == "minimum_commitment_improvement"
    assert result.record.tie_breaks[0].minimum_improvement_eur == 0.01


def test_minimum_benefit_cannot_preserve_invalid_incumbent():
    candidates = _candidate_set()
    outcomes = _outcome_set(candidates)
    outcomes = replace(outcomes, outcomes=(replace(
        outcomes.outcomes[0], validity=CandidateValidity.INVALID,
        invalidity_reasons=("daily_main_goal_unreachable",)), outcomes.outcomes[1]))
    result = EvaluationEngine().evaluate(
        candidates, _strategy(), outcomes, created_at=BASE,
        incumbent_candidate_id="candidate-a", minimum_commitment_improvement_eur=0.01,
    )
    assert result.record.winning_candidate_id == "candidate-b"


def test_missing_optional_benefit_keeps_valid_incumbent():
    candidates = _candidate_set()
    result = EvaluationEngine().evaluate(
        candidates, _strategy(), _outcome_set(candidates), created_at=BASE,
        incumbent_candidate_id="candidate-a", minimum_commitment_improvement_eur=0.01,
    )
    assert result.record.winning_candidate_id == "candidate-a"
    default = EvaluationEngine().evaluate(
        candidates, _strategy(), _outcome_set(candidates), created_at=BASE,
        incumbent_candidate_id="candidate-a",
    )
    assert default.record.winning_candidate_id == "candidate-b"
    assert default.record.evaluation_id != result.record.evaluation_id


@pytest.mark.parametrize("minimum", [float("nan"), float("inf"), -0.01])
def test_invalid_minimum_is_rejected(minimum):
    candidates = _candidate_set()
    with pytest.raises(ValueError, match="finite nonnegative EUR"):
        EvaluationEngine().evaluate(
            candidates, _strategy(), _outcome_set(candidates), created_at=BASE,
            incumbent_candidate_id="candidate-a", minimum_commitment_improvement_eur=minimum,
        )
