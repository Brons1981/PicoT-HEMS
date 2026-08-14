"""ADR-037 household and storage energy requirement derivation."""

from datetime import datetime
from hashlib import sha256

from picot.v2.contracts import (
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)


def derive_projected_household_energy_balance_interval(
    *,
    starts_at: datetime,
    ends_at: datetime,
    current_usable_storage_energy_wh: float,
    expected_usable_pv_energy_wh: float,
    planned_grid_energy_wh: float,
    household_load_forecast_energy_wh: float,
    known_future_demand_energy_wh: float,
    conversion_losses_wh: float,
    other_planned_household_energy_flows_wh: float,
    confidence: float,
    evidence_ids: tuple[str, ...],
) -> ProjectedHouseholdEnergyBalanceInterval:
    projected_storage_energy_wh = (
        current_usable_storage_energy_wh
        + expected_usable_pv_energy_wh
        + planned_grid_energy_wh
        - household_load_forecast_energy_wh
        - known_future_demand_energy_wh
        - conversion_losses_wh
        + other_planned_household_energy_flows_wh
    )
    return ProjectedHouseholdEnergyBalanceInterval(
        starts_at=starts_at,
        ends_at=ends_at,
        current_usable_storage_energy_wh=current_usable_storage_energy_wh,
        expected_usable_pv_energy_wh=expected_usable_pv_energy_wh,
        planned_grid_energy_wh=planned_grid_energy_wh,
        household_load_forecast_energy_wh=household_load_forecast_energy_wh,
        known_future_demand_energy_wh=known_future_demand_energy_wh,
        conversion_losses_wh=conversion_losses_wh,
        other_planned_household_energy_flows_wh=other_planned_household_energy_flows_wh,
        projected_storage_energy_wh=projected_storage_energy_wh,
        confidence=confidence,
        evidence_ids=evidence_ids,
    )


def derive_storage_energy_requirement(
    *,
    balance: ProjectedHouseholdEnergyBalance,
    target_energy_wh: float,
    usable_capacity_wh: float,
    required_by: datetime,
    reason: str,
    reserve_contribution_wh: float,
) -> StorageEnergyRequirement:
    confidence = min(interval.confidence for interval in balance.intervals)
    evidence_ids = tuple(
        dict.fromkeys(
            evidence_id
            for interval in balance.intervals
            for evidence_id in interval.evidence_ids
        )
    )
    seed = (
        f"{balance.balance_id}|{balance.storage_state_id}|"
        f"{target_energy_wh}|{usable_capacity_wh}|{required_by.isoformat()}|"
        f"{reason}|{reserve_contribution_wh}"
    )
    requirement_id = (
        f"storage-requirement-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )
    return StorageEnergyRequirement(
        requirement_id=requirement_id,
        run_id=balance.run_id,
        snapshot_id=balance.snapshot_id,
        storage_state_id=balance.storage_state_id,
        projected_balance_id=balance.balance_id,
        required_energy_wh=target_energy_wh,
        required_soc=target_energy_wh / usable_capacity_wh,
        required_by=required_by,
        reason=reason,
        confidence=confidence,
        evidence_ids=evidence_ids,
        reserve_contribution_wh=reserve_contribution_wh,
    )
