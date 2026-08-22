"""Immutable financial settlement outcome contract from V2ADR-054."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose

EUR_TOLERANCE = 1e-9


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
            (self.grid_import_cost_eur, "Grid import cost"),
            (self.grid_export_value_eur, "Grid export value"),
            (self.avoided_import_value_eur, "Avoided import value"),
            (self.variable_charges_eur, "Variable charges"),
            (self.storage_conversion_loss_cost_eur, "Storage conversion loss cost"),
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
            + self.storage_conversion_loss_cost_eur
            + self.battery_use_cost_eur
        )

    @property
    def minimum_margin_satisfied(self) -> bool:
        return self.net_financial_result_eur >= self.minimum_profit_margin_eur
