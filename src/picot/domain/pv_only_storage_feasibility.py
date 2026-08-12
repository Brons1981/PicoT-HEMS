"""PV-only storage energy feasibility for ADR-037 and ADR-043."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.projected_household_energy_balance import ProjectedHouseholdEnergyBalance
from picot.domain.storage_energy_requirement import StorageEnergyRequirement


class PVOnlyEnergyFeasibilityOutcome(StrEnum):
    """Energy-only PV feasibility result before technical recoverability checks."""

    ENERGY_SUFFICIENT = "energy_sufficient"
    ENERGY_SHORTFALL = "energy_shortfall"


@dataclass(frozen=True, slots=True)
class PVOnlyStorageEnergyFeasibility:
    """Explainable energy-only feasibility for one storage requirement."""

    requirement_id: str
    outcome: PVOnlyEnergyFeasibilityOutcome
    projected_energy_at_protection_start_wh: float
    protection_start_shortfall_wh: float
    household_path_shortfall_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]
    technical_recoverability_evaluated: bool = False

    @property
    def energy_sufficient(self) -> bool:
        return self.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT


@dataclass(frozen=True, slots=True)
class PVOnlyStorageEnergyFeasibilityEvaluator:
    """Evaluate PV-only energy sufficiency from the canonical household balance."""

    method_version: str = "pv-only-storage-energy-feasibility-v2"

    def evaluate(
        self,
        *,
        requirement: StorageEnergyRequirement,
        balance: ProjectedHouseholdEnergyBalance,
        effective_limit: EffectiveStorageLimit,
    ) -> PVOnlyStorageEnergyFeasibility:
        if balance.execution_scope_id != effective_limit.execution_scope_id:
            raise ValueError("Projected balance and effective storage limit must share a scope.")
        if not balance.created_at <= requirement.protection_starts_at <= balance.horizon_end:
            raise ValueError("Storage protection start must be inside the projected balance.")

        boundaries = {balance.created_at, *(point.at for point in balance.points)}
        if requirement.protection_starts_at not in boundaries:
            raise ValueError("Storage protection start must align with a balance boundary.")

        current_energy = min(max(balance.starting_storage_energy_wh, 0.0), effective_limit.max_energy_wh)
        previous_unbounded_energy = balance.starting_storage_energy_wh
        household_path_shortfall_wh = 0.0

        if requirement.protection_starts_at != balance.created_at:
            for point in balance.points:
                delta_wh = point.projected_storage_energy_wh - previous_unbounded_energy
                previous_unbounded_energy = point.projected_storage_energy_wh
                raw_next_energy = current_energy + delta_wh
                if raw_next_energy < 0.0:
                    household_path_shortfall_wh += -raw_next_energy
                current_energy = min(max(raw_next_energy, 0.0), effective_limit.max_energy_wh)
                if point.at == requirement.protection_starts_at:
                    break

        protection_start_shortfall_wh = max(0.0, requirement.required_energy_wh - current_energy)
        energy_sufficient = protection_start_shortfall_wh == 0.0 and household_path_shortfall_wh == 0.0
        outcome = (
            PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT
            if energy_sufficient
            else PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
        )
        evidence_ids = tuple(dict.fromkeys((
            requirement.requirement_id,
            *requirement.evidence_ids,
            balance.balance_id,
            *balance.evidence_ids,
            effective_limit.limit_id,
            *effective_limit.evidence_ids,
            self.method_version,
        )))
        return PVOnlyStorageEnergyFeasibility(
            requirement_id=requirement.requirement_id,
            outcome=outcome,
            projected_energy_at_protection_start_wh=current_energy,
            protection_start_shortfall_wh=protection_start_shortfall_wh,
            household_path_shortfall_wh=household_path_shortfall_wh,
            confidence=min(requirement.confidence, balance.confidence, effective_limit.confidence),
            evidence_ids=evidence_ids,
        )
