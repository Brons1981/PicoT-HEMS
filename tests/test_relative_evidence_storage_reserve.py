from __future__ import annotations

import pytest

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evidence_confidence_policy import (
    EvidenceConfidenceBaseline,
    EvidenceConfidenceDecision,
    RelativeEvidenceConfidencePolicy,
)
from picot.domain.storage_reserve_decision import StorageReserveDecisionPolicy


def _baseline(*, mean: float = 0.82, reliable: bool = True, samples: int = 12):
    return EvidenceConfidenceBaseline(
        baseline_id="baseline-1",
        source_method_id="household-load-v1",
        mean_confidence=mean,
        sample_count=samples,
        reliable=reliable,
        evidence_ids=("history:recent-comparable",),
        method_version="rolling-mean-v1",
    )


def _limit() -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id="battery-1",
        max_soc=0.95,
        usable_capacity_wh=8000.0,
        confidence=1.0,
        evidence_ids=("config:max-soc",),
        method_version="effective-storage-limit-v1",
    )


def test_current_confidence_at_own_mean_allows_lower_target() -> None:
    assessment = RelativeEvidenceConfidencePolicy().assess(
        current_confidence=0.82,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:current",),
        baseline=_baseline(),
    )

    assert assessment.decision is EvidenceConfidenceDecision.LOWER_TARGET_ALLOWED


def test_current_confidence_below_own_mean_requires_conservative_maximum() -> None:
    assessment = RelativeEvidenceConfidencePolicy().assess(
        current_confidence=0.70,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:current",),
        baseline=_baseline(),
    )

    assert assessment.decision is EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED


def test_missing_or_unreliable_baseline_never_validates_low_quality() -> None:
    policy = RelativeEvidenceConfidencePolicy()

    missing = policy.assess(
        current_confidence=0.40,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:fallback",),
        baseline=None,
    )
    unreliable = policy.assess(
        current_confidence=0.40,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:fallback",),
        baseline=_baseline(mean=0.35, reliable=False),
    )

    assert missing.decision is EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED
    assert unreliable.decision is EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED


def test_degraded_evidence_selects_effective_maximum_and_explicit_reserve() -> None:
    assessment = RelativeEvidenceConfidencePolicy().assess(
        current_confidence=0.70,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:current",),
        baseline=_baseline(),
    )

    decision = StorageReserveDecisionPolicy().decide(
        lower_target_energy_wh=5000.0,
        assessment=assessment,
        effective_limit=_limit(),
    )

    assert decision.target_energy_wh == pytest.approx(7600.0)
    assert decision.reserve_energy_wh == pytest.approx(2600.0)
    assert decision.used_effective_maximum is True


def test_sufficient_evidence_uses_balance_derived_lower_target_without_extra_reserve() -> None:
    assessment = RelativeEvidenceConfidencePolicy().assess(
        current_confidence=0.90,
        current_source_method_id="household-load-v1",
        current_evidence_ids=("forecast:current",),
        baseline=_baseline(),
    )

    decision = StorageReserveDecisionPolicy().decide(
        lower_target_energy_wh=5000.0,
        assessment=assessment,
        effective_limit=_limit(),
    )

    assert decision.target_energy_wh == pytest.approx(5000.0)
    assert decision.reserve_energy_wh == 0.0
    assert decision.used_effective_maximum is False
