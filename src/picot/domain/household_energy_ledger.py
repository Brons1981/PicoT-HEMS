"""Immutable conserved household energy-ledger contracts from V2ADR-054."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.discharge_destination_policy import DischargeDestinationPolicy

ENERGY_TOLERANCE_WH = 1e-6


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")


def _non_empty_unique(values: tuple[str, ...], label: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{label} must not contain empty values.")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique.")


@dataclass(frozen=True, slots=True)
class HouseholdEnergyLedgerInterval:
    """One directional, physically conserved household-energy interval."""

    starts_at: datetime
    ends_at: datetime
    household_demand_wh: float
    usable_pv_wh: float
    pv_to_household_wh: float
    pv_to_storage_input_wh: float
    pv_to_grid_wh: float
    curtailed_pv_wh: float
    grid_to_household_wh: float
    grid_to_storage_input_wh: float
    storage_to_household_output_wh: float
    storage_to_grid_output_wh: float
    storage_charge_loss_wh: float
    storage_discharge_loss_wh: float
    unserved_household_energy_wh: float
    storage_energy_at_start_wh: float
    storage_energy_at_end_wh: float
    charge_source_policy: ChargeSourcePolicy | None
    discharge_destination_policy: DischargeDestinationPolicy | None
    confidence: float
    confidence_method_version: str
    capability_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.starts_at, "Ledger interval start")
        _aware(self.ends_at, "Ledger interval end")
        if self.ends_at <= self.starts_at:
            raise ValueError("Ledger interval must end after it starts.")
        for value, label in (
            (self.household_demand_wh, "Household demand"),
            (self.usable_pv_wh, "Usable PV"),
            (self.pv_to_household_wh, "PV to household"),
            (self.pv_to_storage_input_wh, "PV to storage"),
            (self.pv_to_grid_wh, "PV to grid"),
            (self.curtailed_pv_wh, "Curtailed PV"),
            (self.grid_to_household_wh, "Grid to household"),
            (self.grid_to_storage_input_wh, "Grid to storage"),
            (self.storage_to_household_output_wh, "Storage to household"),
            (self.storage_to_grid_output_wh, "Storage to grid"),
            (self.storage_charge_loss_wh, "Storage charge loss"),
            (self.storage_discharge_loss_wh, "Storage discharge loss"),
            (self.unserved_household_energy_wh, "Unserved household energy"),
            (self.storage_energy_at_start_wh, "Storage energy at start"),
            (self.storage_energy_at_end_wh, "Storage energy at end"),
        ):
            if value < 0.0:
                raise ValueError(f"{label} must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Ledger interval confidence must be between 0.0 and 1.0.")
        if not self.confidence_method_version.strip():
            raise ValueError("Confidence method version must not be empty.")
        _non_empty_unique(self.capability_ids, "Capability IDs")
        _non_empty_unique(self.evidence_ids, "Evidence IDs")
        self._validate_policy_permissions()
        self._validate_conservation()

    @property
    def grid_import_wh(self) -> float:
        return self.grid_to_household_wh + self.grid_to_storage_input_wh

    @property
    def grid_export_wh(self) -> float:
        return self.pv_to_grid_wh + self.storage_to_grid_output_wh

    @property
    def storage_charge_input_wh(self) -> float:
        return self.pv_to_storage_input_wh + self.grid_to_storage_input_wh

    @property
    def storage_energy_added_wh(self) -> float:
        return self.storage_charge_input_wh - self.storage_charge_loss_wh

    @property
    def storage_energy_removed_wh(self) -> float:
        return (
            self.storage_to_household_output_wh
            + self.storage_to_grid_output_wh
            + self.storage_discharge_loss_wh
        )

    def _validate_policy_permissions(self) -> None:
        if self.storage_charge_input_wh > ENERGY_TOLERANCE_WH:
            if self.charge_source_policy is None:
                raise ValueError("Storage charging requires an explicit charge source policy.")
            if (
                self.grid_to_storage_input_wh > ENERGY_TOLERANCE_WH
                and not self.charge_source_policy.permits_grid_import
            ):
                raise ValueError(
                    "Charge source policy does not permit grid-to-storage energy."
                )
        if self.storage_energy_removed_wh > ENERGY_TOLERANCE_WH:
            if self.discharge_destination_policy is None:
                raise ValueError(
                    "Storage discharge requires an explicit discharge destination policy."
                )
            if (
                self.storage_to_grid_output_wh > ENERGY_TOLERANCE_WH
                and not self.discharge_destination_policy.permits_grid_export
            ):
                raise ValueError(
                    "Discharge destination policy does not permit storage-to-grid energy."
                )

    def _validate_conservation(self) -> None:
        self._require_close(
            self.usable_pv_wh,
            self.pv_to_household_wh
            + self.pv_to_storage_input_wh
            + self.pv_to_grid_wh
            + self.curtailed_pv_wh,
            "PV conservation",
        )
        if self.storage_charge_loss_wh - self.storage_charge_input_wh > ENERGY_TOLERANCE_WH:
            raise ValueError("Storage charge loss may not exceed storage charge input.")
        self._require_close(
            self.storage_energy_at_end_wh,
            self.storage_energy_at_start_wh
            + self.storage_energy_added_wh
            - self.storage_energy_removed_wh,
            "storage conservation",
        )
        self._require_close(
            self.household_demand_wh,
            self.pv_to_household_wh
            + self.grid_to_household_wh
            + self.storage_to_household_output_wh
            + self.unserved_household_energy_wh,
            "household demand conservation",
        )

    @staticmethod
    def _require_close(expected: float, actual: float, label: str) -> None:
        if not isclose(expected, actual, rel_tol=1e-9, abs_tol=ENERGY_TOLERANCE_WH):
            raise ValueError(f"Ledger {label} failed: expected {expected}, calculated {actual}.")


@dataclass(frozen=True, slots=True)
class HouseholdEnergyLedger:
    """Complete immutable physical ledger for exactly one Candidate Energy Path."""

    ledger_id: str
    run_id: str
    snapshot_id: str
    candidate_id: str
    energy_path_id: str
    horizon_start: datetime
    horizon_end: datetime
    intervals: tuple[HouseholdEnergyLedgerInterval, ...]
    method_version: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.ledger_id, "Ledger ID"),
            (self.run_id, "Run ID"),
            (self.snapshot_id, "Snapshot ID"),
            (self.candidate_id, "Candidate ID"),
            (self.energy_path_id, "Energy Path ID"),
            (self.method_version, "Ledger method version"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty.")
        _aware(self.horizon_start, "Ledger horizon start")
        _aware(self.horizon_end, "Ledger horizon end")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("Ledger horizon must end after it starts.")
        if not self.intervals:
            raise ValueError("Household Energy Ledger requires at least one interval.")
        if self.intervals[0].starts_at != self.horizon_start:
            raise ValueError("Ledger intervals must start at the ledger horizon.")
        if self.intervals[-1].ends_at != self.horizon_end:
            raise ValueError("Ledger intervals must end at the ledger horizon.")
        for left, right in zip(self.intervals, self.intervals[1:], strict=False):
            if left.ends_at != right.starts_at:
                raise ValueError("Ledger intervals must be ordered and contiguous.")
            if not isclose(
                left.storage_energy_at_end_wh,
                right.storage_energy_at_start_wh,
                rel_tol=1e-9,
                abs_tol=ENERGY_TOLERANCE_WH,
            ):
                raise ValueError("Storage energy must remain continuous between intervals.")
