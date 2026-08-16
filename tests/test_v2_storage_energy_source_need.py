from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    CurrentStorageState,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)
from picot.v2.storage_energy_source_need import (
    StorageEnergySourceNeed,
    derive_storage_energy_source_need,
    explain_storage_energy_source_need_nl,
)

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)


def test_adr037_explains_pv_contribution_and_remaining_grid_need() -> None:
    storage = CurrentStorageState(
        storage_state_id="storage-state-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.25,
        usable_capacity_wh=8160.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("zendure-soc",),
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        intervals=(
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=4),
                current_usable_storage_energy_wh=2040.0,
                expected_usable_pv_energy_wh=2500.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=1000.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=3540.0,
                confidence=0.8,
                evidence_ids=("zendure-soc", "solcast", "load-forecast"),
            ),
        ),
    )
    requirement = StorageEnergyRequirement(
        requirement_id="requirement-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        projected_balance_id=balance.balance_id,
        required_energy_wh=8160.0,
        required_soc=1.0,
        required_by=BASE + timedelta(hours=4),
        reason="conservative_effective_maximum",
        confidence=0.8,
        evidence_ids=("zendure-soc", "solcast", "load-forecast"),
        reserve_contribution_wh=4620.0,
    )

    need = derive_storage_energy_source_need(
        storage_state=storage,
        balance=balance,
        requirement=requirement,
    )

    assert need.energy_to_target_wh == 6120.0
    assert need.expected_usable_pv_energy_wh == 2500.0
    assert need.household_load_forecast_energy_wh == 1000.0
    assert need.pv_storage_contribution_wh == 1500.0
    assert need.grid_energy_required_wh == 4620.0
    assert need.pv_only_feasible is False
    assert need.status == "grid_support_required"
    assert need.required_by == BASE + timedelta(hours=4)
    assert need.confidence == 0.8
    assert need.evidence_ids == (
        "zendure-soc",
        "solcast",
        "load-forecast",
    )

    explanation = explain_storage_energy_source_need_nl(
        need,
        storage_name="Zendure",
    )
    assert explanation == (
        "Zendure mist 6,12 kWh om het geplande doel van 8,16 kWh te bereiken. "
        "Van de verwachte 2,50 kWh PV blijft na 1,00 kWh huishoudverbruik "
        "1,50 kWh beschikbaar voor opslag. Daardoor resteert 4,62 kWh "
        "mogelijke netlaadbehoefte vóór 12:00."
    )

    # This is planning evidence, not a charging decision or command.
    assert not hasattr(need, "execution_primitive")
    assert not hasattr(need, "requested_power_w")
    assert not hasattr(need, "selected_price_window")


def test_v2adr050_caps_pv_storage_contribution_and_exposes_low_confidence() -> None:
    storage = CurrentStorageState(
        storage_state_id="storage-state-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.83,
        usable_capacity_wh=8160.0,
        measured_at=BASE,
        confidence=1.0,
        evidence_ids=("zendure-soc",),
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        intervals=(
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=4),
                current_usable_storage_energy_wh=6772.8,
                expected_usable_pv_energy_wh=28731.12,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=9000.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=26503.92,
                confidence=0.0,
                evidence_ids=("zendure-soc", "solcast", "fallback-load"),
            ),
        ),
    )
    requirement = StorageEnergyRequirement(
        requirement_id="requirement-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        projected_balance_id=balance.balance_id,
        required_energy_wh=8160.0,
        required_soc=1.0,
        required_by=BASE + timedelta(hours=4),
        reason="conservative_effective_maximum",
        confidence=0.0,
        evidence_ids=("zendure-soc", "solcast", "fallback-load"),
        reserve_contribution_wh=1387.2,
    )

    need = derive_storage_energy_source_need(
        storage_state=storage,
        balance=balance,
        requirement=requirement,
    )

    assert need.energy_to_target_wh == pytest.approx(1387.2)
    assert need.pv_storage_contribution_wh == need.energy_to_target_wh
    assert need.grid_energy_required_wh == 0.0
    assert need.status == "pv_only_feasible"
    assert need.confidence == 0.0

    assert not hasattr(need, "requested_power_w")


def test_v2adr050_explanation_marks_zero_confidence_as_low() -> None:
    need = StorageEnergySourceNeed(
        storage_state_id="storage-state-home",
        requirement_id="requirement-home",
        projected_balance_id="balance-home",
        target_energy_wh=8160.0,
        energy_to_target_wh=1387.2,
        expected_usable_pv_energy_wh=28731.12,
        household_load_forecast_energy_wh=9000.0,
        pv_storage_contribution_wh=1387.2,
        grid_energy_required_wh=0.0,
        pv_only_feasible=True,
        status="pv_only_feasible",
        required_by=BASE + timedelta(hours=4),
        confidence=0.0,
        evidence_ids=("zendure-soc", "solcast", "fallback-load"),
    )

    explanation = explain_storage_energy_source_need_nl(
        need,
        storage_name="Zendure",
    )
    assert "1,39 kWh beschikbaar voor opslag" in explanation
    assert "Confidence is laag (0%)" in explanation


def test_source_need_ignores_pv_after_storage_deadline() -> None:
    storage = CurrentStorageState(
        storage_state_id="storage-state-home",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.75,
        usable_capacity_wh=8000.0,
        measured_at=BASE,
        confidence=0.8,
        evidence_ids=("storage",),
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id="balance-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        intervals=(
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=1),
                current_usable_storage_energy_wh=6000.0,
                expected_usable_pv_energy_wh=750.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=250.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=6500.0,
                confidence=0.7,
                evidence_ids=("pv-before", "load-before"),
            ),
            ProjectedHouseholdEnergyBalanceInterval(
                starts_at=BASE + timedelta(hours=1),
                ends_at=BASE + timedelta(hours=2),
                current_usable_storage_energy_wh=6500.0,
                expected_usable_pv_energy_wh=5000.0,
                planned_grid_energy_wh=0.0,
                household_load_forecast_energy_wh=0.0,
                known_future_demand_energy_wh=0.0,
                conversion_losses_wh=0.0,
                other_planned_household_energy_flows_wh=0.0,
                projected_storage_energy_wh=11500.0,
                confidence=0.9,
                evidence_ids=("pv-after",),
            ),
        ),
    )
    requirement = StorageEnergyRequirement(
        requirement_id="requirement-home",
        run_id="run-1",
        snapshot_id="snapshot-1",
        storage_state_id=storage.storage_state_id,
        projected_balance_id=balance.balance_id,
        required_energy_wh=8000.0,
        required_soc=1.0,
        required_by=BASE + timedelta(hours=1),
        reason="full_before_support",
        confidence=0.7,
        evidence_ids=("storage", "pv-before", "load-before"),
        reserve_contribution_wh=1500.0,
    )

    need = derive_storage_energy_source_need(
        storage_state=storage,
        balance=balance,
        requirement=requirement,
    )

    assert need.expected_usable_pv_energy_wh == 750.0
    assert need.household_load_forecast_energy_wh == 250.0
    assert need.pv_storage_contribution_wh == 500.0
    assert need.grid_energy_required_wh == 1500.0
    assert need.status == "grid_support_required"
    assert "pv-after" not in need.evidence_ids
