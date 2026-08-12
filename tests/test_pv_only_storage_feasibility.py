from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.effective_storage_limit import EffectiveStorageLimit
from picot.domain.projected_household_energy_balance import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalancePoint,
)
from picot.domain.pv_only_storage_feasibility import (
    PVOnlyEnergyFeasibilityOutcome,
    PVOnlyStorageEnergyFeasibilityEvaluator,
)
from picot.domain.storage_energy_requirement import (
    StorageEnergyRequirement,
    StorageRequirementReason,
)


START = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
T1 = START + timedelta(hours=1)
T2 = START + timedelta(hours=2)
T3 = START + timedelta(hours=3)


def _limit(max_soc: float = 1.0) -> EffectiveStorageLimit:
    return EffectiveStorageLimit(
        limit_id="limit-1",
        execution_scope_id="battery-1",
        max_soc=max_soc,
        usable_capacity_wh=8000.0,
        confidence=0.95,
        evidence_ids=("limit:evidence",),
        method_version="limit-v1",
    )


def _requirement(
    *, protection_starts_at: datetime = T2, energy_wh: float = 5000.0
) -> StorageEnergyRequirement:
    return StorageEnergyRequirement(
        requirement_id="requirement-1",
        protection_starts_at=protection_starts_at,
        protected_through=T3,
        required_energy_wh=energy_wh,
        required_soc_percent=energy_wh / 80.0,
        reason=StorageRequirementReason.HOUSEHOLD_DEMAND,
        confidence=0.9,
        evidence_ids=("requirement:evidence",),
    )


def _balance(*, starting: float, positions: tuple[float, ...]) -> ProjectedHouseholdEnergyBalance:
    times = (T1, T2, T3)[: len(positions)]
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-1",
        created_at=START,
        horizon_end=times[-1],
        execution_scope_id="battery-1",
        starting_storage_energy_wh=starting,
        points=tuple(
            ProjectedHouseholdEnergyBalancePoint(
                at=at,
                projected_storage_energy_wh=energy,
                cumulative_pv_energy_wh=0.0,
                cumulative_household_load_wh=0.0,
            )
            for at, energy in zip(times, positions, strict=True)
        ),
        confidence=0.85,
        evidence_ids=("balance:evidence",),
    )


def test_pv_only_energy_is_sufficient_when_complete_path_and_protection_start_are_covered() -> None:
    result = PVOnlyStorageEnergyFeasibilityEvaluator().evaluate(
        requirement=_requirement(),
        balance=_balance(starting=4000.0, positions=(5200.0, 6000.0, 3000.0)),
        effective_limit=_limit(),
    )

    assert result.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SUFFICIENT
    assert result.projected_energy_at_protection_start_wh == pytest.approx(6000.0)
    assert result.protection_start_shortfall_wh == 0.0
    assert result.household_path_shortfall_wh == 0.0
    assert result.technical_recoverability_evaluated is False


def test_protection_start_target_shortfall_is_explicit() -> None:
    result = PVOnlyStorageEnergyFeasibilityEvaluator().evaluate(
        requirement=_requirement(energy_wh=6000.0),
        balance=_balance(starting=4000.0, positions=(4500.0, 5000.0, 3000.0)),
        effective_limit=_limit(),
    )

    assert result.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
    assert result.protection_start_shortfall_wh == pytest.approx(1000.0)


def test_earlier_household_path_shortfall_is_not_hidden_by_later_pv_recovery() -> None:
    result = PVOnlyStorageEnergyFeasibilityEvaluator().evaluate(
        requirement=_requirement(energy_wh=3000.0),
        balance=_balance(starting=1000.0, positions=(-500.0, 3500.0, 2000.0)),
        effective_limit=_limit(),
    )

    assert result.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
    assert result.projected_energy_at_protection_start_wh == pytest.approx(4000.0)
    assert result.protection_start_shortfall_wh == 0.0
    assert result.household_path_shortfall_wh == pytest.approx(500.0)


def test_storage_ceiling_prevents_spilled_pv_from_being_reused_later() -> None:
    result = PVOnlyStorageEnergyFeasibilityEvaluator().evaluate(
        requirement=_requirement(energy_wh=7000.0),
        balance=_balance(starting=7500.0, positions=(12000.0, 7000.0, 5000.0)),
        effective_limit=_limit(),
    )

    assert result.outcome is PVOnlyEnergyFeasibilityOutcome.ENERGY_SHORTFALL
    assert result.projected_energy_at_protection_start_wh == pytest.approx(3000.0)
    assert result.protection_start_shortfall_wh == pytest.approx(4000.0)


def test_requirement_protection_start_must_match_balance_boundary() -> None:
    with pytest.raises(ValueError, match="align with a balance boundary"):
        PVOnlyStorageEnergyFeasibilityEvaluator().evaluate(
            requirement=_requirement(
                protection_starts_at=START + timedelta(minutes=30)
            ),
            balance=_balance(starting=4000.0, positions=(5000.0, 6000.0, 3000.0)),
            effective_limit=_limit(),
        )
