from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)

BASE = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def test_projected_balance_and_storage_requirement_are_immutable_and_traceable() -> None:
    evidence_ids = (
        "storage-state:home-battery",
        "household-load:forecast-1",
        "pv-energy:timeline-1",
    )
    interval = ProjectedHouseholdEnergyBalanceInterval(
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=4),
        current_usable_storage_energy_wh=3200.0,
        expected_usable_pv_energy_wh=1500.0,
        planned_grid_energy_wh=0.0,
        household_load_forecast_energy_wh=2600.0,
        known_future_demand_energy_wh=400.0,
        conversion_losses_wh=100.0,
        other_planned_household_energy_flows_wh=0.0,
        projected_storage_energy_wh=1600.0,
        confidence=0.80,
        evidence_ids=evidence_ids,
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-1",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id="storage-state-1",
        intervals=(interval,),
    )
    requirement = StorageEnergyRequirement(
        requirement_id="requirement-1",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id="storage-state-1",
        projected_balance_id=balance.balance_id,
        required_energy_wh=2448.0,
        required_soc=0.30,
        required_by=interval.ends_at,
        reason="HOUSEHOLD_AND_RESERVE",
        confidence=interval.confidence,
        evidence_ids=interval.evidence_ids,
        reserve_contribution_wh=816.0,
    )

    assert interval.projected_storage_energy_wh == pytest.approx(
        3200.0 + 1500.0 - 2600.0 - 400.0 - 100.0
    )
    assert balance.intervals == (interval,)
    assert requirement.projected_balance_id == balance.balance_id
    assert requirement.required_energy_wh == pytest.approx(2448.0)
    assert requirement.required_soc == pytest.approx(0.30)
    assert requirement.required_by == BASE + timedelta(hours=4)
    assert requirement.confidence == pytest.approx(0.80)
    assert requirement.reserve_contribution_wh == pytest.approx(816.0)
    assert requirement.evidence_ids == evidence_ids

    with pytest.raises(FrozenInstanceError):
        setattr(requirement, "required_energy_wh", 0.0)
