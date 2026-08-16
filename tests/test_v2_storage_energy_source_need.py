from datetime import UTC, datetime, timedelta

from picot.v2.storage_energy_source_need import (
    derive_storage_energy_source_need,
    explain_storage_energy_source_need_nl,
)

from picot.v2.contracts import (
    CurrentStorageState,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
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
        "Zendure mist 6120 Wh om het geplande doel van 8160 Wh te bereiken. "
        "Van de verwachte 2500 Wh PV blijft na 1000 Wh huishoudverbruik "
        "1500 Wh beschikbaar voor opslag. Daardoor resteert 4620 Wh "
        "mogelijke netlaadbehoefte vóór 12:00."
    )

    # This is planning evidence, not a charging decision or command.
    assert not hasattr(need, "execution_primitive")
    assert not hasattr(need, "requested_power_w")
    assert not hasattr(need, "selected_price_window")
