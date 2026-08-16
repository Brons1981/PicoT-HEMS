"""ADR-037 storage energy-source need and plain-language explanation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.v2.contracts import (
    CurrentStorageState,
    ProjectedHouseholdEnergyBalance,
    StorageEnergyRequirement,
)


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True, slots=True)
class StorageEnergySourceNeed:
    """Traceable source split before Candidate construction or execution."""

    storage_state_id: str
    requirement_id: str
    projected_balance_id: str
    target_energy_wh: float
    energy_to_target_wh: float
    expected_usable_pv_energy_wh: float
    household_load_forecast_energy_wh: float
    pv_storage_contribution_wh: float
    grid_energy_required_wh: float
    pv_only_feasible: bool
    status: str
    required_by: datetime
    confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str = "storage-energy-source-need:v1"

    def __post_init__(self) -> None:
        values = (
            self.target_energy_wh,
            self.energy_to_target_wh,
            self.expected_usable_pv_energy_wh,
            self.household_load_forecast_energy_wh,
            self.pv_storage_contribution_wh,
            self.grid_energy_required_wh,
        )
        if any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("energy values must be finite and non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.required_by.tzinfo is None or self.required_by.utcoffset() is None:
            raise ValueError("required_by must be timezone-aware")
        if self.status not in {
            "target_already_met",
            "pv_only_feasible",
            "grid_support_required",
        }:
            raise ValueError("storage source-need status is invalid")
        if self.pv_only_feasible != (
            self.status in {"target_already_met", "pv_only_feasible"}
        ):
            raise ValueError("PV-only feasibility and status must agree")
        if not self.evidence_ids:
            raise ValueError("evidence lineage must not be empty")
        if not self.method_version.strip():
            raise ValueError("method_version must be explicit")


def derive_storage_energy_source_need(
    *,
    storage_state: CurrentStorageState,
    balance: ProjectedHouseholdEnergyBalance,
    requirement: StorageEnergyRequirement,
) -> StorageEnergySourceNeed:
    """Derive source need without selecting a Candidate or command."""

    if balance.storage_state_id != storage_state.storage_state_id:
        raise ValueError("balance must reference the supplied storage state")
    if requirement.storage_state_id != storage_state.storage_state_id:
        raise ValueError("requirement must reference the supplied storage state")
    if requirement.projected_balance_id != balance.balance_id:
        raise ValueError("requirement must reference the supplied balance")
    if requirement.run_id != balance.run_id:
        raise ValueError("requirement and balance run lineage must match")
    if requirement.snapshot_id != balance.snapshot_id:
        raise ValueError("requirement and balance snapshot lineage must match")
    if not balance.intervals:
        raise ValueError("projected balance intervals are required")

    current_energy_wh = storage_state.current_stored_energy_wh
    target_energy_wh = requirement.required_energy_wh
    energy_to_target_wh = max(0.0, target_energy_wh - current_energy_wh)
    expected_pv_wh = sum(
        interval.expected_usable_pv_energy_wh
        for interval in balance.intervals
    )
    household_load_wh = sum(
        interval.household_load_forecast_energy_wh
        for interval in balance.intervals
    )
    planned_grid_wh = sum(
        interval.planned_grid_energy_wh
        for interval in balance.intervals
    )
    if planned_grid_wh != 0.0:
        raise ValueError(
            "source need must be derived before grid energy is planned"
        )

    projected_energy_wh = balance.intervals[-1].projected_storage_energy_wh
    pv_storage_contribution_wh = min(
        energy_to_target_wh,
        max(
            0.0,
            projected_energy_wh - current_energy_wh,
        ),
    )
    grid_energy_required_wh = max(
        0.0,
        target_energy_wh - projected_energy_wh,
    )

    if energy_to_target_wh == 0.0:
        status = "target_already_met"
    elif grid_energy_required_wh == 0.0:
        status = "pv_only_feasible"
    else:
        status = "grid_support_required"

    evidence_ids = _ordered_unique(
        storage_state.evidence_ids
        + requirement.evidence_ids
        + tuple(
            evidence_id
            for interval in balance.intervals
            for evidence_id in interval.evidence_ids
        )
    )
    confidence = min(
        storage_state.confidence,
        requirement.confidence,
        *(interval.confidence for interval in balance.intervals),
    )
    return StorageEnergySourceNeed(
        storage_state_id=storage_state.storage_state_id,
        requirement_id=requirement.requirement_id,
        projected_balance_id=balance.balance_id,
        target_energy_wh=target_energy_wh,
        energy_to_target_wh=energy_to_target_wh,
        expected_usable_pv_energy_wh=expected_pv_wh,
        household_load_forecast_energy_wh=household_load_wh,
        pv_storage_contribution_wh=pv_storage_contribution_wh,
        grid_energy_required_wh=grid_energy_required_wh,
        pv_only_feasible=status != "grid_support_required",
        status=status,
        required_by=requirement.required_by,
        confidence=confidence,
        evidence_ids=evidence_ids,
    )


def _energy_kwh_nl(value_wh: float) -> str:
    return f"{value_wh / 1000.0:.2f}".replace(".", ",") + " kWh"


def explain_storage_energy_source_need_nl(
    need: StorageEnergySourceNeed,
    *,
    storage_name: str,
) -> str:
    """Render deterministic Dutch explanation without adding decisions."""

    name = storage_name.strip()
    if not name:
        raise ValueError("storage_name must not be empty")
    deadline = need.required_by.strftime("%H:%M")
    prefix = (
        f"{name} mist {_energy_kwh_nl(need.energy_to_target_wh)} om het "
        f"geplande doel van {_energy_kwh_nl(need.target_energy_wh)} te bereiken. "
    )
    pv = (
        f"Van de verwachte {_energy_kwh_nl(need.expected_usable_pv_energy_wh)} "
        f"PV blijft na {_energy_kwh_nl(need.household_load_forecast_energy_wh)} "
        f"huishoudverbruik {_energy_kwh_nl(need.pv_storage_contribution_wh)} "
        "beschikbaar voor opslag. "
    )
    if need.status == "grid_support_required":
        return (
            prefix
            + pv
            + f"Daardoor resteert {_energy_kwh_nl(need.grid_energy_required_wh)} "
            f"mogelijke netlaadbehoefte vóór {deadline}."
        )
    if need.status == "pv_only_feasible":
        explanation = (
            prefix
            + pv
            + f"De verwachte PV kan het geplande doel vóór {deadline} "
            "zonder netladen bereiken."
        )
        if need.confidence == 0.0:
            explanation += " Confidence is laag (0%)."
        return explanation
    return (
        f"{name} heeft het geplande doel van "
        f"{_energy_kwh_nl(need.target_energy_wh)} al bereikt; "
        "er is geen aanvullende laadenergie nodig."
    )
