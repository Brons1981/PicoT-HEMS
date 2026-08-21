from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)
from picot.v2.energy_requirements import (
    derive_projected_household_energy_balance_interval,
    derive_storage_energy_requirement,
)

BASE = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def boundary_balance() -> ProjectedHouseholdEnergyBalance:
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
        evidence_ids=("storage-state:home-battery",),
    )
    return ProjectedHouseholdEnergyBalance(
        balance_id="balance-boundary",
        run_id="run-boundary",
        snapshot_id="snapshot-boundary",
        storage_state_id="storage-state-boundary",
        intervals=(interval,),
    )


def test_projected_household_balance_interval_is_derived_deterministically() -> None:
    def derive() -> ProjectedHouseholdEnergyBalanceInterval:
        return derive_projected_household_energy_balance_interval(
            starts_at=BASE,
            ends_at=BASE + timedelta(hours=4),
            current_usable_storage_energy_wh=3200.0,
            expected_usable_pv_energy_wh=1500.0,
            planned_grid_energy_wh=0.0,
            household_load_forecast_energy_wh=2600.0,
            known_future_demand_energy_wh=400.0,
            conversion_losses_wh=100.0,
            other_planned_household_energy_flows_wh=0.0,
            confidence=0.80,
            evidence_ids=(
                "storage-state:home-battery",
                "household-load:forecast-1",
                "pv-energy:timeline-1",
            ),
        )

    first = derive()
    second = derive()

    assert first == second
    assert first.projected_storage_energy_wh == pytest.approx(
        3200.0 + 1500.0 - 2600.0 - 400.0 - 100.0
    )
    assert first.confidence == pytest.approx(0.80)
    assert first.evidence_ids == (
        "storage-state:home-battery",
        "household-load:forecast-1",
        "pv-energy:timeline-1",
    )


def test_storage_requirement_derivation_is_deterministic_and_traceable() -> None:
    def derive() -> StorageEnergyRequirement:
        interval = derive_projected_household_energy_balance_interval(
            starts_at=BASE,
            ends_at=BASE + timedelta(hours=4),
            current_usable_storage_energy_wh=3200.0,
            expected_usable_pv_energy_wh=1500.0,
            planned_grid_energy_wh=0.0,
            household_load_forecast_energy_wh=2600.0,
            known_future_demand_energy_wh=400.0,
            conversion_losses_wh=100.0,
            other_planned_household_energy_flows_wh=0.0,
            confidence=0.80,
            evidence_ids=(
                "storage-state:home-battery",
                "household-load:forecast-1",
                "pv-energy:timeline-1",
            ),
        )
        balance = ProjectedHouseholdEnergyBalance(
            balance_id="balance-1",
            run_id="run-1",
            snapshot_id="snapshot-1",
            storage_state_id="storage-state-1",
            intervals=(interval,),
        )
        return derive_storage_energy_requirement(
            balance=balance,
            target_energy_wh=2448.0,
            usable_capacity_wh=8160.0,
            required_by=interval.ends_at,
            reason="HOUSEHOLD_AND_RESERVE",
            reserve_contribution_wh=816.0,
        )

    first = derive()
    second = derive()

    assert first == second
    assert first.requirement_id.startswith("storage-requirement-")
    assert first.run_id == "run-1"
    assert first.snapshot_id == "snapshot-1"
    assert first.storage_state_id == "storage-state-1"
    assert first.projected_balance_id == "balance-1"
    assert first.required_energy_wh == pytest.approx(2448.0)
    assert first.required_soc == pytest.approx(0.30)
    assert first.required_by == BASE + timedelta(hours=4)
    assert first.reason == "HOUSEHOLD_AND_RESERVE"
    assert first.confidence == pytest.approx(0.80)
    assert first.evidence_ids == (
        "storage-state:home-battery",
        "household-load:forecast-1",
        "pv-energy:timeline-1",
    )
    assert first.reserve_contribution_wh == pytest.approx(816.0)
    assert first.confidence_method_version == (
        "storage-requirement-energy-weighted-confidence:v1"
    )


def test_negligible_weak_interval_does_not_dominate_requirement_confidence() -> None:
    intervals = tuple(
        derive_projected_household_energy_balance_interval(
            starts_at=BASE + timedelta(hours=index),
            ends_at=BASE + timedelta(hours=index + 1),
            current_usable_storage_energy_wh=3200.0,
            expected_usable_pv_energy_wh=pv_wh,
            planned_grid_energy_wh=0.0,
            household_load_forecast_energy_wh=0.0,
            known_future_demand_energy_wh=0.0,
            conversion_losses_wh=0.0,
            other_planned_household_energy_flows_wh=0.0,
            confidence=confidence,
            evidence_ids=(f"interval-{index}",),
        )
        for index, (pv_wh, confidence) in enumerate(((1.0, 0.10), (1000.0, 0.90)))
    )
    balance = ProjectedHouseholdEnergyBalance(
        "balance-weighted",
        "run-weighted",
        "snapshot-weighted",
        "storage-weighted",
        intervals,
    )

    requirement = derive_storage_energy_requirement(
        balance=balance,
        target_energy_wh=1000.0,
        usable_capacity_wh=8160.0,
        required_by=intervals[-1].ends_at,
        reason="WEIGHTED_CONFIDENCE",
        reserve_contribution_wh=0.0,
    )

    assert requirement.confidence == pytest.approx(
        (1.0 * 0.10 + 1000.0 * 0.90) / 1001.0
    )
    assert requirement.confidence > 0.89


@pytest.mark.parametrize(
    ("target_energy_wh", "usable_capacity_wh", "message"),
    (
        (-1.0, 8160.0, "target_energy_wh must be non-negative"),
        (8161.0, 8160.0, "target_energy_wh must not exceed usable_capacity_wh"),
        (2448.0, 0.0, "usable_capacity_wh must be positive"),
    ),
)
def test_storage_requirement_rejects_invalid_energy_boundaries(
    target_energy_wh: float,
    usable_capacity_wh: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        derive_storage_energy_requirement(
            balance=boundary_balance(),
            target_energy_wh=target_energy_wh,
            usable_capacity_wh=usable_capacity_wh,
            required_by=BASE + timedelta(hours=4),
            reason="HOUSEHOLD_AND_RESERVE",
            reserve_contribution_wh=816.0,
        )


def test_storage_requirement_rejects_balance_without_intervals() -> None:
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-empty",
        run_id="run-empty",
        snapshot_id="snapshot-empty",
        storage_state_id="storage-state-empty",
        intervals=(),
    )

    with pytest.raises(ValueError, match="balance must contain at least one interval"):
        derive_storage_energy_requirement(
            balance=balance,
            target_energy_wh=2448.0,
            usable_capacity_wh=8160.0,
            required_by=BASE + timedelta(hours=4),
            reason="HOUSEHOLD_AND_RESERVE",
            reserve_contribution_wh=816.0,
        )


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
        requirement.required_energy_wh = 0.0  # type: ignore[misc]
