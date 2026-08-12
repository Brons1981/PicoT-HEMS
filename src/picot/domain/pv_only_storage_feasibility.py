"""PV-only storage energy feasibility for ADR-037."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
)
from picot.domain.storage_energy_requirement import StorageEnergyRequirement


class PVOnlyEnergyFeasibilityOutcome(StrEnum):
    """Energy-only PV feasibility result before technical recoverability checks."""

    ENERGY_SUFFICIENT = "energy_sufficient"
    ENERGY_SHORTFALL = "energy_shortfall"


@dataclass(frozen=True, slots=True)
class PVOnlyStorageEnergyFeasibility:
    """Explainable energy-only feasibility for one storage requirement.

    The calculation uses the canonical no-grid projected household balance and
    enforces the effective storage ceiling interval by interval. It therefore
    does not treat gross PV as battery-available energy and does not retain PV
    that would have been spilled after storage reached its effective maximum.

    This result deliberately does not claim technical recoverability. Charge
    power, device limits and other capability constraints remain a later check.
    """

    requirement_id: str
    outcome: PVOnlyEnergyFeasibilityOutcome
    projected_energy_at_deadline_wh: float
    deadline_shortfall_wh: float
    household_path_shortfall_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]
    technical_recoverability_evaluated: bool = False

    @property
    def energy_sufficient(self) -> bool:
        """Return whether PV/current storage cover the complete path and target."""

        return self.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT


@dataclass(frozen=True, slots=True)
class PVOnlyStorageEnergyFeasibilityEvaluator:
    """Evaluate PV-only energy sufficiency from the canonical household balance."""

    method_version: str = "pv-only-storage-energy-feasibility-v1"

    def evaluate(
        self,
        *,
        requirement: StorageEnergyRequirement,
        balance: ProjectedHouseholdEnergyBalance,
        effective_limit: EffectiveStorageLimit,
    ) -> PVOnlyStorageEnergyFeasibility:
        if balance.execution_scope_id != effective_limit.execution_scope_id:
            raise ValueError("Projected balance and effective storage limit must share a scope.")
        if not balance.created_at <= requirement.required_by <= balance.horizon_end:
            raise ValueError("Storage requirement deadline must be inside the projected balance.")

        deadline_boundaries = {balance.created_at, *(point.at for point in balance.points)}
        if requirement.required_by not in deadline_boundaries:
            raise ValueError("Storage requirement deadline must align with a balance boundary.")

        current_energy = min(
            max(balance.starting_storage_energy_wh, 0.0),
            effective_limit.max_energy_wh,
        )
        previous_unbounded_energy = balance.starting_storage_energy_wh
        household_path_shortfall_wh = 0.0

        if requirement.required_by != balance.created_at:
            for point in balance.points:
                delta_wh = point.projected_storage_energy_wh - previous_unbounded_energy
                previous_unbounded_energy = point.projected_storage_energy_wh

                raw_next_energy = current_energy + delta_wh
                if raw_next_energy < 0.0:
                    household_path_shortfall_wh += -raw_next_energy

                current_energy = min(
                    max(raw_next_energy, 0.0),
                    effective_limit.max_energy_wh,
                )
                if point.at == requirement.required_by:
                    break

        deadline_shortfall_wh = max(
            0.0,
            requirement.required_energy_wh - current_energy,
        )
        energy_sufficient = (
            deadline_shortfall_wh == 0.0 and household_path_shortfall_wh == 0.0
        )
        outcome = (
            PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT
            if energy_sufficient
            else PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    requirement.requirement_id,
                    *requirement.evidence_ids,
                    balance.balance_id,
                    *balance.evidence_ids,
                    effective_limit.limit_id,
                    *effective_limit.evidence_ids,
                    self.method_version,
                )
            )
        )
        return PVOnlyStorageEnergyFeasibility(
            requirement_id=requirement.requirement_id,
            outcome=outcome,
            projected_energy_at_deadline_wh=current_energy,
            deadline_shortfall_wh=deadline_shortfall_wh,
            household_path_shortfall_wh=household_path_shortfall_wh,
            confidence=min(
                requirement.confidence,
                balance.confidence,
                effective_limit.confidence,
            ),
            evidence_ids=evidence_ids,
        )
