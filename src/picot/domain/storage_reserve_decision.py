"""Confidence-aware storage reserve target decision for ADR-037."""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evidence_confidence_policy import (
    EvidenceConfidenceAssessment,
    EvidenceConfidenceDecision,
)


@dataclass(frozen=True, slots=True)
class StorageReserveDecision:
    """Target-energy boundary used by StorageEnergyRequirement derivation.

    This object decides only whether the effective maximum remains mandatory or
    whether a lower balance-derived target may be used. It does not choose a
    charging source, Candidate or execution command.
    """

    target_energy_wh: float
    reserve_energy_wh: float
    used_effective_maximum: bool
    confidence: float
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageReserveDecisionPolicy:
    """Apply the relative evidence assessment to one lower target proposal."""

    method_version: str = "storage-reserve-decision-v1"

    def decide(
        self,
        *,
        lower_target_energy_wh: float,
        assessment: EvidenceConfidenceAssessment,
        effective_limit: EffectiveStorageLimit,
    ) -> StorageReserveDecision:
        if lower_target_energy_wh < 0:
            raise ValueError("Lower storage target energy must not be negative.")
        if lower_target_energy_wh > effective_limit.max_energy_wh:
            raise ValueError("Lower storage target may not exceed the effective maximum.")

        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *assessment.evidence_ids,
                    effective_limit.limit_id,
                    *effective_limit.evidence_ids,
                    self.method_version,
                )
            )
        )
        confidence = min(assessment.current_confidence, effective_limit.confidence)
        if assessment.decision is EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED:
            return StorageReserveDecision(
                target_energy_wh=effective_limit.max_energy_wh,
                reserve_energy_wh=effective_limit.max_energy_wh - lower_target_energy_wh,
                used_effective_maximum=True,
                confidence=confidence,
                reason=assessment.reason,
                evidence_ids=evidence_ids,
            )

        return StorageReserveDecision(
            target_energy_wh=lower_target_energy_wh,
            reserve_energy_wh=0.0,
            used_effective_maximum=False,
            confidence=confidence,
            reason=assessment.reason,
            evidence_ids=evidence_ids,
        )
