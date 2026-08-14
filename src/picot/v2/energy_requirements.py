"""ADR-037 household and storage energy requirement derivation."""

from datetime import datetime

from picot.v2.contracts import ProjectedHouseholdEnergyBalanceInterval


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
