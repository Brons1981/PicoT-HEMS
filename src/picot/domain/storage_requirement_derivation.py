"""Derive ADR-037 StorageEnergyRequirement from canonical planning evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evidence_confidence_policy import EvidenceConfidenceAssessment
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
)
from picot.domain.storage_energy_requirement import (
    StorageEnergyRequirement,
    StorageRequirementReason,
)
from picot.domain.storage_reserve_decision import (
    StorageReserveDecision,
    StorageReserveDecisionPolicy,
)


@dataclass(frozen=True, slots=True)
class BalanceStorageTargetProposal:
    """Balance-derived lower storage target and the time it must be available."""

    required_by: datetime
    target_energy_wh: float
    projected_drawdown_wh: float
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageRequirementDeriver:
    """Map canonical balance and reserve evidence to one storage requirement."""

    method_version: str = "storage-requirement-derivation-v1"

    def propose_lower_target(
        self,
        *,
        balance: ProjectedHouseholdEnergyBalance,
        effective_limit: EffectiveStorageLimit,
    ) -> BalanceStorageTargetProposal:
        if balance.execution_scope_id != effective_limit.execution_scope_id:
            raise ValueError("Projected balance and effective storage limit must share a scope.")

        positions = (
            (balance.created_at, balance.starting_storage_energy_wh),
            *((point.at, point.projected_storage_energy_wh) for point in balance.points),
        )

        best_required_by = balance.created_at
        best_drawdown = 0.0
        for index, (at, energy_wh) in enumerate(positions[:-1]):
            minimum_after = min(value for _, value in positions[index + 1 :])
            drawdown = max(0.0, energy_wh - minimum_after)
            if drawdown > best_drawdown:
                best_drawdown = drawdown
                best_required_by = at

        target_energy_wh = min(best_drawdown, effective_limit.max_energy_wh)
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    balance.balance_id,
                    *balance.evidence_ids,
                    effective_limit.limit_id,
                    *effective_limit.evidence_ids,
                    self.method_version,
                )
            )
        )
        return BalanceStorageTargetProposal(
            required_by=best_required_by,
            target_energy_wh=target_energy_wh,
            projected_drawdown_wh=best_drawdown,
            evidence_ids=evidence_ids,
        )

    def derive(
        self,
        *,
        requirement_id: str,
        balance: ProjectedHouseholdEnergyBalance,
        effective_limit: EffectiveStorageLimit,
        confidence_assessment: EvidenceConfidenceAssessment,
        reserve_policy: StorageReserveDecisionPolicy | None = None,
    ) -> StorageEnergyRequirement:
        proposal = self.propose_lower_target(
            balance=balance,
            effective_limit=effective_limit,
        )
        policy = reserve_policy or StorageReserveDecisionPolicy()
        reserve_decision: StorageReserveDecision = policy.decide(
            lower_target_energy_wh=proposal.target_energy_wh,
            assessment=confidence_assessment,
            effective_limit=effective_limit,
        )

        required_soc_percent = (
            reserve_decision.target_energy_wh / effective_limit.usable_capacity_wh * 100.0
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *proposal.evidence_ids,
                    *reserve_decision.evidence_ids,
                    self.method_version,
                )
            )
        )
        reason = (
            StorageRequirementReason.CONSERVATIVE_RESERVE
            if reserve_decision.used_effective_maximum
            else StorageRequirementReason.HOUSEHOLD_DEMAND
        )
        return StorageEnergyRequirement(
            requirement_id=requirement_id,
            required_by=proposal.required_by,
            required_energy_wh=reserve_decision.target_energy_wh,
            required_soc_percent=required_soc_percent,
            reason=reason,
            confidence=min(balance.confidence, reserve_decision.confidence),
            evidence_ids=evidence_ids,
            reserve_energy_wh=reserve_decision.reserve_energy_wh,
        )
