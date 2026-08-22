"""Observer-only canonical financial settlement producer from V2ADR-054."""

from __future__ import annotations

from picot.domain.energy_contract import EnergyContractSnapshot, EnergyTariffInterval
from picot.domain.financial_settlement import (
    FinancialSettlementInterval,
    FinancialSettlementOutcome,
)
from picot.domain.household_energy_ledger import (
    HouseholdEnergyLedger,
    HouseholdEnergyLedgerInterval,
)

METHOD_VERSION = "canonical-energy-contract-settlement:v1"


class CanonicalFinancialSettlementProducer:
    """Value completed ledger flows without changing their physical allocation."""

    def settle(
        self,
        *,
        ledger: HouseholdEnergyLedger,
        contract: EnergyContractSnapshot,
        minimum_profit_margin_eur: float = 0.0,
        battery_use_cost_eur: float = 0.0,
    ) -> FinancialSettlementOutcome:
        if minimum_profit_margin_eur < 0.0:
            raise ValueError("Minimum profit margin must not be negative.")
        if battery_use_cost_eur < 0.0:
            raise ValueError("Battery use cost must not be negative.")
        tariffs = {(item.starts_at, item.ends_at): item for item in contract.intervals}
        intervals: list[FinancialSettlementInterval] = []
        for physical in ledger.intervals:
            tariff = tariffs.get((physical.starts_at, physical.ends_at))
            if tariff is None:
                raise ValueError(
                    "Financial settlement requires exact tariff evidence for every "
                    "ledger interval."
                )
            intervals.append(self._settle_interval(physical=physical, tariff=tariff))

        interval_tuple = tuple(intervals)
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    ledger.ledger_id,
                    contract.contract_snapshot_id,
                    contract.settlement_rule_id,
                    contract.contract_version,
                    *(evidence for item in interval_tuple for evidence in item.evidence_ids),
                )
            )
        )
        grid_import_cost_eur = sum(item.grid_import_cost_eur for item in interval_tuple)
        grid_export_result_eur = sum(item.grid_export_result_eur for item in interval_tuple)
        avoided_import_value_eur = sum(
            item.avoided_import_value_eur for item in interval_tuple
        )
        variable_charges_eur = sum(item.variable_charges_eur for item in interval_tuple)
        foregone_export_result_eur = sum(
            item.foregone_export_result_eur for item in interval_tuple
        )
        net_result_eur = (
            grid_export_result_eur
            + avoided_import_value_eur
            - grid_import_cost_eur
            - variable_charges_eur
            - foregone_export_result_eur
            - battery_use_cost_eur
        )
        return FinancialSettlementOutcome(
            settlement_id=f"settlement:{ledger.ledger_id}:{contract.contract_snapshot_id}",
            ledger_id=ledger.ledger_id,
            contract_snapshot_id=contract.contract_snapshot_id,
            grid_import_energy_wh=sum(item.grid_import_energy_wh for item in interval_tuple),
            grid_export_energy_wh=sum(item.grid_export_energy_wh for item in interval_tuple),
            grid_import_cost_eur=grid_import_cost_eur,
            grid_export_value_eur=grid_export_result_eur,
            avoided_import_value_eur=avoided_import_value_eur,
            variable_charges_eur=variable_charges_eur,
            storage_conversion_loss_cost_eur=sum(
                item.storage_conversion_loss_cost_eur for item in interval_tuple
            ),
            battery_use_cost_eur=battery_use_cost_eur,
            minimum_profit_margin_eur=minimum_profit_margin_eur,
            net_financial_result_eur=net_result_eur,
            confidence=min(item.confidence for item in interval_tuple),
            settlement_method_version=METHOD_VERSION,
            evidence_ids=evidence_ids,
            foregone_export_result_eur=foregone_export_result_eur,
            intervals=interval_tuple,
        )

    @staticmethod
    def _settle_interval(
        *,
        physical: HouseholdEnergyLedgerInterval,
        tariff: EnergyTariffInterval,
    ) -> FinancialSettlementInterval:
        vat_factor = 1.0 if tariff.price_components_include_vat else 1.0 + tariff.vat_rate
        import_energy_rate = vat_factor * (
            tariff.commodity_import_eur_per_kwh
            + tariff.energy_tax_import_eur_per_kwh
        )
        import_variable_rate = vat_factor * (
            tariff.supplier_import_eur_per_kwh
            + tariff.transaction_fee_import_eur_per_kwh
        )
        export_result_rate = vat_factor * (
            tariff.commodity_export_eur_per_kwh
            + tariff.supplier_export_eur_per_kwh
        )
        export_variable_rate = vat_factor * (
            tariff.export_charge_eur_per_kwh
            + tariff.transaction_fee_export_eur_per_kwh
        )
        complete_import_rate = import_energy_rate + import_variable_rate
        complete_export_result_rate = export_result_rate - export_variable_rate

        charge_input_wh = physical.storage_charge_input_wh
        grid_charge_share = (
            physical.grid_to_storage_input_wh / charge_input_wh
            if charge_input_wh > 0.0
            else 0.0
        )
        pv_charge_share = (
            physical.pv_to_storage_input_wh / charge_input_wh
            if charge_input_wh > 0.0
            else 0.0
        )
        grid_charge_loss_wh = physical.storage_charge_loss_wh * grid_charge_share
        pv_charge_loss_wh = physical.storage_charge_loss_wh * pv_charge_share
        conversion_loss_cost_eur = (
            grid_charge_loss_wh * complete_import_rate
            + pv_charge_loss_wh * complete_export_result_rate
            + physical.storage_discharge_loss_wh * complete_import_rate
        ) / 1000.0

        evidence_ids = tuple(
            dict.fromkeys((*physical.evidence_ids, *tariff.evidence_ids))
        )
        return FinancialSettlementInterval(
            starts_at=physical.starts_at,
            ends_at=physical.ends_at,
            grid_import_energy_wh=physical.grid_import_wh,
            grid_export_energy_wh=physical.grid_export_wh,
            pv_to_storage_input_wh=physical.pv_to_storage_input_wh,
            storage_conversion_loss_energy_wh=(
                physical.storage_charge_loss_wh + physical.storage_discharge_loss_wh
            ),
            grid_import_cost_eur=physical.grid_import_wh * import_energy_rate / 1000.0,
            grid_export_result_eur=physical.grid_export_wh * export_result_rate / 1000.0,
            avoided_import_value_eur=(
                physical.storage_to_household_output_wh * complete_import_rate / 1000.0
            ),
            variable_charges_eur=(
                physical.grid_import_wh * import_variable_rate
                + physical.grid_export_wh * export_variable_rate
            )
            / 1000.0,
            foregone_export_result_eur=(
                physical.pv_to_storage_input_wh * complete_export_result_rate / 1000.0
            ),
            storage_conversion_loss_cost_eur=conversion_loss_cost_eur,
            confidence=min(physical.confidence, tariff.confidence),
            evidence_ids=evidence_ids,
        )
