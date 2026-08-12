from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import EnergyPath, PathSegment
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.storage_technical_recoverability import StorageTechnicalRecoverability
from picot.planner.adr037_candidate_outcome_derivation import ADR037CandidateOutcomeDeriver
from picot.planner.evaluation_engine import EvaluationEngine


BASE = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
PROTECTION_START = BASE + timedelta(hours=4)
PROTECTED_THROUGH = BASE + timedelta(hours=8)


def _candidate_set(*, grid_supported: bool) -> CandidateSet:
    if grid_supported:
        family = CandidateFamily.COST_FIRST
        policy = ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
    else:
        family = CandidateFamily.PV_FIRST
        policy = ChargeSourcePolicy.PV_ONLY

    path = EnergyPath(
        path_id="path-1",
        snapshot_id="snapshot-1",
        family=family,
        horizon_start=BASE,
        horizon_end=BASE + timedelta(hours=24),
        segments=(
            PathSegment(
                segment_id="segment-1",
                order=1,
                execution_scope_id="battery-main",
                starts_at=BASE + timedelta(hours=1),
                ends_at=BASE + timedelta(hours=2),
                primitive=ExecutionPrimitive.CHARGE_AT_POWER,
                capability_id="battery-charge",
                purpose="test",
                evidence_ids=("evidence-1",),
                requested_power_w=1500.0,
                charge_source_policy=policy,
            ),
        ),
        projected_states=(),
        opportunity_ids=("opportunity-1",),
        constraint_ids=(),
        capability_ids=("battery-charge",),
        strategy_version=1,
        mapping_version=1,
        assumptions=("test",),
        confidence=0.9,
    )
    candidate = Candidate(
        candidate_id="candidate-1",
        snapshot_id="snapshot-1",
        family=family,
        energy_path_id=path.path_id,
        opportunity_ids=path.opportunity_ids,
        constraint_ids=path.constraint_ids,
        strategy_version=1,
        capability_ids=path.capability_ids,
        assumptions=path.assumptions,
        confidence=path.confidence,
    )
    return CandidateSet(
        snapshot_id="snapshot-1",
        strategy_version=1,
        candidates=(candidate,),
        energy_paths=(path,),
        exclusions=(),
    )


def _recoverability(*, technically_recoverable: bool = True) -> StorageTechnicalRecoverability:
    return StorageTechnicalRecoverability(
        evaluated_at=BASE,
        requirement_id="requirement-1",
        capability_id="battery-charge",
        protection_starts_at=PROTECTION_START,
        protected_through=PROTECTED_THROUGH,
        extra_energy_required_wh=3000.0,
        additional_acquisition_required=True,
        maximum_charge_energy_before_protection_wh=4000.0,
        latest_full_power_charge_start=BASE + timedelta(hours=2),
        technically_recoverable=technically_recoverable,
        confidence=0.84,
        evidence_ids=("requirement-1", "battery-charge"),
    )


def test_pv_only_outcome_does_not_invent_objective_or_recoverability_values() -> None:
    candidate_set = _candidate_set(grid_supported=False)
    result = ADR037CandidateOutcomeDeriver().derive(candidate_set=candidate_set)

    outcome = result.outcomes[0]
    assert outcome.objective_outcomes == ()
    assert outcome.recoverability is None
    assert outcome.execution_complexity == 2
    assert outcome.expected_switching_count is None
    assert result.candidate_set_reference == EvaluationEngine.candidate_set_reference(candidate_set)


def test_grid_supported_outcome_carries_technical_recoverability_confidence() -> None:
    result = ADR037CandidateOutcomeDeriver().derive(
        candidate_set=_candidate_set(grid_supported=True),
        storage_recoverability=_recoverability(),
    )

    outcome = result.outcomes[0]
    assert outcome.recoverability == pytest.approx(0.84)
    assert outcome.objective_outcomes == ()
    assert "requirement-1" in outcome.evidence_ids


def test_grid_supported_outcome_requires_recoverability_evidence() -> None:
    with pytest.raises(ValueError, match="require technical recoverability"):
        ADR037CandidateOutcomeDeriver().derive(
            candidate_set=_candidate_set(grid_supported=True)
        )


def test_grid_supported_outcome_rejects_non_recoverable_evidence() -> None:
    with pytest.raises(ValueError, match="non-recoverable"):
        ADR037CandidateOutcomeDeriver().derive(
            candidate_set=_candidate_set(grid_supported=True),
            storage_recoverability=_recoverability(technically_recoverable=False),
        )
