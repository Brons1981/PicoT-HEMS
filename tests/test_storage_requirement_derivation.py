from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.evidence_confidence_policy import (
    EvidenceConfidenceAssessment,
    EvidenceConfidenceDecision,
)
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalancePoint,
)
from picot.domain.storage_energy_requirement import StorageRequirementReason
from picot.domain.storage_requirement_derivation import StorageRequirementDeriver


START = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _balance() -> ProjectedHouseholdEnergyBalance:
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-1",
        created_at=START,
        horizon_end=START + timedelta(hours=6),
        execution_scope_id="battery-1",
        starting_storage_energy_wh=4000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=1),
                projected_storage_energy_wh=5000.0,
                cumulative_pv_energy_wh=1500.0,
                cumulative_household_load_wh=500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=2),
                projected_storage_energy_wh=6500.0,
                cumulative_pv_energy_wh=3500.0,
                cumulative_household_load_wh=1000.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=4),
                projected_storage_energy_wh=3500.0,
                cumulative_pv_energy_wh=4000.0,
                cumulative_household_load_wh=4500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=6),
                projected_storage_energy_wh=1500.0,
                cumulative_pv_energy_wh=4000.0,
                cumulative_household_load_wh=6500.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("balance:evidence",),
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


def _assessment(*, lower_allowed: bool) -> EvidenceConfidenceAssessment:
    decision = (
        EvidenceConfidenceDecision.LOWER_TARGET_ALLOWED
        if lower_allowed
        else EvidenceConfidenceDecision.CONSERVATIVE_MAXIMUM_REQUIRED
    )
    return EvidenceConfidenceAssessment(
        decision=decision,
        current_confidence=0.8,
        baseline_mean_confidence=0.75,
        baseline_id="baseline-1",
        reason=(
            "current_confidence_at_or_above_own_reliable_mean"
            if lower_allowed
            else "current_confidence_below_own_reliable_mean"
        ),
        evidence_ids=("confidence:evidence",),
    )


def test_lower_target_is_largest_future_drawdown_with_explicit_protection_interval() -> None:
    proposal = StorageRequirementDeriver().propose_lower_target(
        balance=_balance(),
        effective_limit=_limit(),
    )

    assert proposal.protection_starts_at == START + timedelta(hours=2)
    assert proposal.protected_through == START + timedelta(hours=6)
    assert proposal.projected_drawdown_wh == pytest.approx(5000.0)
    assert proposal.target_energy_wh == pytest.approx(5000.0)


def test_reliable_evidence_maps_lower_balance_target_to_storage_requirement() -> None:
    requirement = StorageRequirementDeriver().derive(
        requirement_id="req-1",
        balance=_balance(),
        effective_limit=_limit(),
        confidence_assessment=_assessment(lower_allowed=True),
    )

    assert requirement.protection_starts_at == START + timedelta(hours=2)
    assert requirement.protected_through == START + timedelta(hours=6)
    assert requirement.required_energy_wh == pytest.approx(5000.0)
    assert requirement.required_soc_percent == pytest.approx(62.5)
    assert requirement.reserve_energy_wh == 0.0
    assert requirement.reason is StorageRequirementReason.HOUSEHOLD_DEMAND


def test_degraded_evidence_keeps_same_protection_interval_but_raises_target() -> None:
    requirement = StorageRequirementDeriver().derive(
        requirement_id="req-1",
        balance=_balance(),
        effective_limit=_limit(),
        confidence_assessment=_assessment(lower_allowed=False),
    )

    assert requirement.protection_starts_at == START + timedelta(hours=2)
    assert requirement.protected_through == START + timedelta(hours=6)
    assert requirement.required_energy_wh == pytest.approx(7600.0)
    assert requirement.required_soc_percent == pytest.approx(95.0)
    assert requirement.reserve_energy_wh == pytest.approx(2600.0)
    assert requirement.reason is StorageRequirementReason.CONSERVATIVE_RESERVE


def test_fresh_later_snapshot_recomputes_only_remaining_future_drawdown() -> None:
    earlier = ProjectedHouseholdEnergyBalance(
        balance_id="balance-earlier",
        created_at=START,
        horizon_end=START + timedelta(hours=6),
        execution_scope_id="battery-1",
        starting_storage_energy_wh=6000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=2),
                projected_storage_energy_wh=6000.0,
                cumulative_pv_energy_wh=0.0,
                cumulative_household_load_wh=0.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=6),
                projected_storage_energy_wh=4000.0,
                cumulative_pv_energy_wh=0.0,
                cumulative_household_load_wh=2000.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("snapshot:earlier",),
    )
    later_start = START + timedelta(hours=3)
    later = ProjectedHouseholdEnergyBalance(
        balance_id="balance-later",
        created_at=later_start,
        horizon_end=START + timedelta(hours=6),
        execution_scope_id="battery-1",
        starting_storage_energy_wh=5500.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=6),
                projected_storage_energy_wh=4000.0,
                cumulative_pv_energy_wh=0.0,
                cumulative_household_load_wh=1500.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("snapshot:later",),
    )

    deriver = StorageRequirementDeriver()
    earlier_proposal = deriver.propose_lower_target(balance=earlier, effective_limit=_limit())
    later_proposal = deriver.propose_lower_target(balance=later, effective_limit=_limit())

    assert earlier_proposal.target_energy_wh == pytest.approx(2000.0)
    assert later_proposal.target_energy_wh == pytest.approx(1500.0)
    assert later_proposal.target_energy_wh < earlier_proposal.target_energy_wh
    assert later_proposal.protection_starts_at == later_start
    assert later_proposal.protected_through == START + timedelta(hours=6)


def test_target_is_capped_at_effective_storage_limit_but_drawdown_remains_visible() -> None:
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-large-drawdown",
        created_at=START,
        horizon_end=START + timedelta(hours=2),
        execution_scope_id="battery-1",
        starting_storage_energy_wh=9000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=1),
                projected_storage_energy_wh=9500.0,
                cumulative_pv_energy_wh=1000.0,
                cumulative_household_load_wh=500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=2),
                projected_storage_energy_wh=-500.0,
                cumulative_pv_energy_wh=1000.0,
                cumulative_household_load_wh=10500.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("balance:evidence",),
    )

    proposal = StorageRequirementDeriver().propose_lower_target(
        balance=balance,
        effective_limit=_limit(),
    )

    assert proposal.protection_starts_at == START + timedelta(hours=1)
    assert proposal.protected_through == START + timedelta(hours=2)
    assert proposal.projected_drawdown_wh == pytest.approx(10000.0)
    assert proposal.target_energy_wh == pytest.approx(7600.0)


def test_flat_or_rising_balance_uses_horizon_end_with_zero_requirement() -> None:
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-no-drawdown",
        created_at=START,
        horizon_end=START + timedelta(hours=2),
        execution_scope_id="battery-1",
        starting_storage_energy_wh=4000.0,
        points=(
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=1),
                projected_storage_energy_wh=4500.0,
                cumulative_pv_energy_wh=1000.0,
                cumulative_household_load_wh=500.0,
            ),
            ProjectedHouseholdEnergyBalancePoint(
                at=START + timedelta(hours=2),
                projected_storage_energy_wh=5000.0,
                cumulative_pv_energy_wh=2000.0,
                cumulative_household_load_wh=1000.0,
            ),
        ),
        confidence=0.8,
        evidence_ids=("balance:evidence",),
    )

    proposal = StorageRequirementDeriver().propose_lower_target(
        balance=balance,
        effective_limit=_limit(),
    )

    assert proposal.protection_starts_at == balance.horizon_end
    assert proposal.protected_through == balance.horizon_end
    assert proposal.projected_drawdown_wh == 0.0
    assert proposal.target_energy_wh == 0.0
