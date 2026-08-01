from __future__ import annotations

import pytest

from picot.domain.candidate import (
    Candidate,
    CandidateExclusion,
    CandidateExclusionKind,
    CandidateFamily,
    CandidateSet,
)


def _candidate() -> Candidate:
    return Candidate(
        candidate_id="candidate-1",
        snapshot_id="snapshot-1",
        family=CandidateFamily.COST_FIRST,
        energy_path_id="energy-path-1",
        opportunity_ids=("opportunity-1",),
        constraint_ids=("constraint-1",),
        strategy_version=3,
        capability_ids=("capability-battery-charge",),
        assumptions=("Forecast remains valid for the planning horizon.",),
        confidence=0.82,
    )


def test_candidate_set_preserves_traceability() -> None:
    candidate = _candidate()
    exclusion = CandidateExclusion(
        family=CandidateFamily.PV_FIRST,
        kind=CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE,
        reason="No PV opportunity is available.",
        source_ids=("opportunity-set-1",),
    )

    result = CandidateSet(
        snapshot_id="snapshot-1",
        strategy_version=3,
        candidates=(candidate,),
        exclusions=(exclusion,),
    )

    assert result.candidates[0].energy_path_id == "energy-path-1"
    assert result.candidates[0].opportunity_ids == ("opportunity-1",)
    assert result.exclusions[0].kind is CandidateExclusionKind.OBJECTIVELY_IMPOSSIBLE


def test_candidate_rejects_duplicate_capability_ids() -> None:
    with pytest.raises(ValueError, match="capability IDs must be unique"):
        Candidate(
            candidate_id="candidate-1",
            snapshot_id="snapshot-1",
            family=CandidateFamily.COST_FIRST,
            energy_path_id="energy-path-1",
            opportunity_ids=(),
            constraint_ids=(),
            strategy_version=1,
            capability_ids=("capability-1", "capability-1"),
            assumptions=(),
            confidence=1.0,
        )


def test_candidate_set_rejects_snapshot_mismatch() -> None:
    with pytest.raises(ValueError, match="Candidate Set snapshot"):
        CandidateSet(
            snapshot_id="snapshot-2",
            strategy_version=3,
            candidates=(_candidate(),),
            exclusions=(),
        )


def test_candidate_set_rejects_strategy_version_mismatch() -> None:
    with pytest.raises(ValueError, match="Candidate Set strategy version"):
        CandidateSet(
            snapshot_id="snapshot-1",
            strategy_version=4,
            candidates=(_candidate(),),
            exclusions=(),
        )
