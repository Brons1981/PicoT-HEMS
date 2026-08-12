"""Relative evidence-confidence policy for conservative storage planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceConfidenceDecision(StrEnum):
    """Whether evidence supports planning below the effective storage maximum."""

    LOWER_TARGET_ALLOWED = "lower_target_allowed"
    CONSERVATIVE_MAXIMUM_REQUIRED = "conservative_maximum_required"


@dataclass(frozen=True, slots=True)
class EvidenceConfidenceBaseline:
    """Reliable recent baseline for one evidence source/method.

    The baseline confidence is the rolling mean of comparable, accepted evidence
    quality for the same source/method. Reliability is supplied explicitly so a
    degraded or undersampled baseline can never validate itself merely because
    its own mean is low.
    """

    baseline_id: str
    source_method_id: str
    mean_confidence: float
    sample_count: int
    reliable: bool
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.baseline_id.strip():
            raise ValueError("Evidence baseline ID must not be empty.")
        if not self.source_method_id.strip():
            raise ValueError("Evidence source/method ID must not be empty.")
        if not 0.0 <= self.mean_confidence <= 1.0:
            raise ValueError("Evidence baseline mean confidence must be between 0.0 and 1.0.")
        if self.sample_count < 0:
            raise ValueError("Evidence baseline sample count must not be negative.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Evidence baseline evidence IDs must not be empty.")
        if not self.method_version.strip():
            raise ValueError("Evidence baseline method version must not be empty.")


@dataclass(frozen=True, slots=True)
class EvidenceConfidenceAssessment:
    """Explainable comparison of current confidence against its own baseline."""

    decision: EvidenceConfidenceDecision
    current_confidence: float
    baseline_mean_confidence: float | None
    baseline_id: str | None
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelativeEvidenceConfidencePolicy:
    """Compare current evidence quality with its own reliable recent mean.

    No fixed global confidence threshold is used. A lower storage target is
    permitted only when the current confidence is at least the reliable rolling
    mean for the same source/method. Missing, unreliable or source-mismatched
    baselines fall back to the conservative maximum target.
    """

    method_version: str = "relative-evidence-confidence-v1"

    def assess(
        self,
        *,
        current_confidence: float,
        current_source_method_id: str,
        current_evidence_ids: tuple[str, ...],
        baseline: EvidenceConfidenceBaseline | None,
    ) -> EvidenceConfidenceAssessment:
        if not 0.0 <= current_confidence <= 1.0:
            raise ValueError("Current evidence confidence must be between 0.0 and 1.0.")
        if not current_source_method_id.strip():
            raise ValueError("Current evidence source/method ID must not be empty.")
        if any(not evidence_id.strip() for evidence_id in current_evidence_ids):
            raise ValueError("Current evidence IDs must not be empty.")

        evidence_ids = (*current_evidence_ids, self.method_version)
        if baseline is None:
            return EvidenceConfidenceAssessment(
                decision=EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED,
                current_confidence=current_confidence,
                baseline_mean_confidence=None,
                baseline_id=None,
                reason="no_reliable_baseline_available",
                evidence_ids=evidence_ids,
            )
        if baseline.source_method_id != current_source_method_id:
            raise ValueError("Current evidence and baseline must use the same source/method.")

        evidence_ids = (*evidence_ids, baseline.baseline_id, *baseline.evidence_ids)
        if not baseline.reliable or baseline.sample_count == 0:
            return EvidenceConfidenceAssessment(
                decision=EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED,
                current_confidence=current_confidence,
                baseline_mean_confidence=baseline.mean_confidence,
                baseline_id=baseline.baseline_id,
                reason="baseline_degraded_or_undersampled",
                evidence_ids=evidence_ids,
            )
        if current_confidence < baseline.mean_confidence:
            return EvidenceConfidenceAssessment(
                decision=EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED,
                current_confidence=current_confidence,
                baseline_mean_confidence=baseline.mean_confidence,
                baseline_id=baseline.baseline_id,
                reason="current_confidence_below_own_reliable_mean",
                evidence_ids=evidence_ids,
            )
        return EvidenceConfidenceAssessment(
            decision=EvidenceConfidenceDecision.LOWER_TARGET_ALLOWED,
            current_confidence=current_confidence,
            baseline_mean_confidence=baseline.mean_confidence,
            baseline_id=baseline.baseline_id,
            reason="current_confidence_at_or_above_own_reliable_mean",
            evidence_ids=evidence_ids,
        )
