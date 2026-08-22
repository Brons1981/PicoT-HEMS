"""Immutable financial settlement contracts from V2ADR-054."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isclose

EUR_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class FinancialSettlementInterval:
    """Traceable tariff valuation of one immutable physical-ledger interval."""

    starts_at: datetime
    ends_at: datetime
    grid_import_energy_wh: float
    grid_export_energy_wh: float
    pv_to_storage_input_wh: float
    storage_conversion_loss_energy_wh: float
    grid_import_cost_eur: float
    grid_export_result_eur: float
    avoided_import_value_eur: float
    variable_charges_eur: float
    foregone_export_result_eur: float
    storage_conversion_loss_cost_eur: float
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError("Settlement interval start must be timezone-aware.")
        if self.ends_at.tzinfo is None or self.ends_at.utcoffset() is None:
            raise ValueError("Settlement interval end must be timezone-aware.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Settlement interval must end after it starts.")
        for numeric_value, label in (
            (self.grid_import_energy_wh, "Grid import energy"),
            (self.grid_export_energy_wh, "Grid export energy"),
            (self.pv_to_storage_input_wh, "PV-to-storage energy"),
            (self.storage_conversion_loss_energy_wh, "Storage conversion loss energy"),
        ):
            if numeric_value < 0.0:
                raise ValueError(f"{label} must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Settlement interval confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Settlement interval evidence IDs must contain non-empty values.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Settlement interval evidence IDs must be unique.")


@dataclass(frozen=True, slots=True)
class FinancialSettlementOutcome:
    """Traceable financial result derived from one completed physical ledger."""

    settlement_id: str
    ledger_id: str
    contract_snapshot_id: str
    grid_import_energy_wh: float
    grid_export_energy_wh: float
    grid_import_cost_eur: float
    grid_export_value_eur: float
    avoided_import_value_eur: float
    variable_charges_eur: float
    storage_conversion_loss_cost_eur: float
    battery_use_cost_eur: float
    minimum_profit_margin_eur: float
    net_financial_result_eur: float
    confidence: float
    settlement_method_version: str
    evidence_ids: tuple[str, ...]
    foregone_export_result_eur: float = 0.0
    intervals: tuple[FinancialSettlementInterval, ...] = ()

    def __post_init__(self) -> None:
        for text_value, label in (
            (self.settlement_id, "Settlement ID"),
            (self.ledger_id, "Ledger ID"),
            (self.contract_snapshot_id, "Contract Snapshot ID"),
            (self.settlement_method_version, "Settlement method version"),
        ):
            if not text_value.strip():
                raise ValueError(f"{label} must not be empty.")
        for numeric_value, label in (
            (self.grid_import_energy_wh, "Grid import energy"),
            (self.grid_export_energy_wh, "Grid export energy"),
            (self.battery_use_cost_eur, "Battery use cost"),
            (self.minimum_profit_margin_eur, "Minimum profit margin"),
        ):
            if numeric_value < 0.0:
                raise ValueError(f"{label} must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Settlement confidence must be between 0.0 and 1.0.")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Settlement evidence IDs must contain non-empty values.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Settlement evidence IDs must be unique.")
        if self.intervals:
            if any(
                left.ends_at != right.starts_at
                for left, right in zip(self.intervals, self.intervals[1:], strict=False)
            ):
                raise ValueError("Settlement intervals must be ordered and contiguous.")
            self._require_interval_total(
                self.grid_import_energy_wh,
                sum(item.grid_import_energy_wh for item in self.intervals),
                "grid import energy",
            )
            self._require_interval_total(
                self.grid_export_energy_wh,
                sum(item.grid_export_energy_wh for item in self.intervals),
                "grid export energy",
            )
            for expected, actual, label in (
                (
                    self.grid_import_cost_eur,
                    sum(item.grid_import_cost_eur for item in self.intervals),
                    "grid import cost",
                ),
                (
                    self.grid_export_value_eur,
                    sum(item.grid_export_result_eur for item in self.intervals),
                    "grid export result",
                ),
                (
                    self.avoided_import_value_eur,
                    sum(item.avoided_import_value_eur for item in self.intervals),
                    "avoided import value",
                ),
                (
                    self.variable_charges_eur,
                    sum(item.variable_charges_eur for item in self.intervals),
                    "variable charges",
                ),
                (
                    self.foregone_export_result_eur,
                    sum(item.foregone_export_result_eur for item in self.intervals),
                    "foregone export result",
                ),
                (
                    self.storage_conversion_loss_cost_eur,
                    sum(
                        item.storage_conversion_loss_cost_eur
                        for item in self.intervals
                    ),
                    "storage conversion loss cost",
                ),
            ):
                self._require_interval_total(expected, actual, label)
        if not isclose(
            self.net_financial_result_eur,
            self.gross_market_benefit_eur - self.total_variable_cost_eur,
            rel_tol=1e-9,
            abs_tol=EUR_TOLERANCE,
        ):
            raise ValueError("Settlement net financial result does not reconcile.")

    @property
    def gross_market_benefit_eur(self) -> float:
        return self.grid_export_value_eur + self.avoided_import_value_eur

    @property
    def total_variable_cost_eur(self) -> float:
        return (
            self.grid_import_cost_eur
            + self.variable_charges_eur
            + self.battery_use_cost_eur
            + self.foregone_export_result_eur
        )

    @staticmethod
    def _require_interval_total(expected: float, actual: float, label: str) -> None:
        if not isclose(expected, actual, rel_tol=1e-9, abs_tol=EUR_TOLERANCE):
            raise ValueError(f"Settlement interval {label} does not reconcile.")

    @property
    def minimum_margin_satisfied(self) -> bool:
        return self.net_financial_result_eur >= self.minimum_profit_margin_eur
