from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import Candidate, CandidateFamily
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.evaluation import (
    EvaluationOutcomeStatus,
    EvaluationRecord,
    EvaluationResult,
)
from picot.domain.execution_plan import ExecutionPlanLifecycle
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.execution_plan_builder import ExecutionPlanBuilder

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _record(candidate_id: str | None) -> EvaluationRecord:
    return EvaluationRecord(
        evaluation_id="evaluation-1",
        schema_version=1,
        snapshot_id="snapshot-1",
        strategy_version=2,
        candidate_set_reference="candidate-set-1",
        evaluated_candidate_ids=("candidate-1",),
        invalid_candidates=(),
        strategic_objective_order=(),
        objective_comparisons=(),
        tie_breaks=(),
        decisive_step="tie_break:candidate_identifier" if candidate_id else None,
        winning_candidate_id=candidate_id,
        created_at=BASE,
        implementation_version="evaluation-v1",
    )


def _winner(*, with_segments: bool = True) -> EvaluationResult:
    segments: tuple[PathSegment, ...] = ()
    capability_ids: tuple[str, ...] = ()
    if with_segments:
        segments = (
            PathSegment(
                segment_id="path-segment-battery",
                order=1,
                execution_scope_id="battery-main",
                starts_at=BASE + timedelta(hours=1),
                ends_at=BASE + timedelta(hours=2),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER,
                capability_id="battery-charge",
                purpose="Use PV surplus",
                evidence_ids=("opportunity-pv-1",),
                requested_power_w=1200.0,
                charge_source_policy=ChargeSourcePolicy.PV_ONLY,
            ),
            PathSegment(
                segment_id="path-segment-ev",
                order=2,
                execution_scope_id="ev-main",
                starts_at=BASE + timedelta(hours=2),
                ends_at=BASE + timedelta(hours=3),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER,
                capability_id="ev-charge",
                purpose="Charge flexible load",
                evidence_ids=("opportunity-flex-1",),
                requested_power_w=1800.0,
                charge_source_policy=ChargeSourcePolicy.PV_ONLY,
            ),
        )
        capability_ids = ("battery-charge", "ev-charge")
    path = EnergyPath(
        path_id="path-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.PV_FIRST,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=24),
        segments=segments,
        projected_states=(),
        opportunity_ids=(),
        constraint_ids=(),
        capability_ids=capability_ids,
        strategy_version=2,
        mapping_version=3,
        assumptions=(),
        confidence=0.9,
    )
    candidate = Candidate(
        candidate_id="candidate-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.PV_FIRST,
        energy_path_id="path-1",
        opportunity_ids=(),
        constraint_ids=(),
        strategy_version=2,
        capability_ids=capability_ids,
        assumptions=(),
        confidence=0.9,
    )
    return EvaluationResult(
        status=EvaluationOutcomeStatus.WINNER_SELECTED,
        record=_record("candidate-1"),
        winning_candidate=candidate,
        winning_energy_path=path,
    )


def test_builder_creates_one_plan_per_scope_and_preserves_segments() -> None:
    result = ExecutionPlanBuilder().build(
        _winner(),
        created_at=BASE,
        fallback_policy_id="fallback-safe-v1",
    )

    assert [plan.execution_scope_id for plan in result.plans] == [
        "battery-main",
        "ev-main",
    ]
    battery = result.plans[0]
    assert battery.lifecycle is ExecutionPlanLifecycle.PROPOSED
    assert battery.revision == 1
    assert battery.segments[0].source_path_segment_id == "path-segment-battery"
    assert battery.segments[0].requested_power_w == 1200.0


def test_builder_returns_empty_plan_set_for_baseline_path() -> None:
    result = ExecutionPlanBuilder().build(
        _winner(with_segments=False),
        created_at=BASE,
        fallback_policy_id="fallback-safe-v1",
    )

    assert result.plans == ()
    assert result.winning_energy_path_id == "path-1"


def test_builder_is_deterministic() -> None:
    first = ExecutionPlanBuilder().build(
        _winner(),
        created_at=BASE,
        fallback_policy_id="fallback-safe-v1",
    )
    second = ExecutionPlanBuilder().build(
        _winner(),
        created_at=BASE,
        fallback_policy_id="fallback-safe-v1",
    )

    assert first == second


def test_builder_rejects_no_valid_candidate_result() -> None:
    no_winner = EvaluationResult(
        status=EvaluationOutcomeStatus.NO_VALID_CANDIDATE,
        record=_record(None),
        winning_candidate=None,
        winning_energy_path=None,
    )

    with pytest.raises(ValueError, match="winner-selected"):
        ExecutionPlanBuilder().build(
            no_winner,
            created_at=BASE,
            fallback_policy_id="fallback-safe-v1",
        )


def test_builder_requires_explicit_fallback_policy() -> None:
    with pytest.raises(ValueError, match="Fallback policy"):
        ExecutionPlanBuilder().build(
            _winner(),
            created_at=BASE,
            fallback_policy_id="",
        )
