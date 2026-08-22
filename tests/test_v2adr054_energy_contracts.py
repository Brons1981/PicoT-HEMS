from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.discharge_destination_policy import DischargeDestinationPolicy
from picot.domain.energy_contract import EnergyContractSnapshot, EnergyTariffInterval
from picot.domain.financial_settlement import FinancialSettlementOutcome
from picot.domain.household_energy_ledger import (
    HouseholdEnergyLedger,
    HouseholdEnergyLedgerInterval,
)
from picot.planner.canonical_financial_settlement import (
    CanonicalFinancialSettlementProducer,
)

BASE = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def _interval(**overrides: object) -> HouseholdEnergyLedgerInterval:
    values: dict[str, object] = {
        "starts_at": BASE,
        "ends_at": BASE + timedelta(minutes=15),
        "household_demand_wh": 700.0,
        "usable_pv_wh": 1000.0,
        "pv_to_household_wh": 300.0,
        "pv_to_storage_input_wh": 400.0,
        "pv_to_grid_wh": 200.0,
        "curtailed_pv_wh": 100.0,
        "grid_to_household_wh": 250.0,
        "grid_to_storage_input_wh": 100.0,
        "storage_to_household_output_wh": 150.0,
        "storage_to_grid_output_wh": 0.0,
        "storage_charge_loss_wh": 50.0,
        "storage_discharge_loss_wh": 50.0,
        "unserved_household_energy_wh": 0.0,
        "storage_energy_at_start_wh": 2000.0,
        "storage_energy_at_end_wh": 2250.0,
        "charge_source_policy": ChargeSourcePolicy.GRID_ALLOWED_FOR_REQUIREMENT,
        "discharge_destination_policy": DischargeDestinationPolicy.HOUSEHOLD_ONLY,
        "confidence": 0.8,
        "confidence_method_version": "ledger-required-input-min:v1",
        "capability_ids": ("storage-main", "grid-main"),
        "evidence_ids": ("pv:q1", "load:q1", "tariff:q1"),
    }
    values.update(overrides)
    return HouseholdEnergyLedgerInterval(**values)  # type: ignore[arg-type]


def test_interval_preserves_directional_flows_and_conserves_energy() -> None:
    interval = _interval()

    assert interval.grid_import_wh == pytest.approx(350.0)
    assert interval.grid_export_wh == pytest.approx(200.0)
    assert interval.storage_charge_input_wh == pytest.approx(500.0)
    assert interval.storage_energy_added_wh == pytest.approx(450.0)
    assert interval.storage_energy_removed_wh == pytest.approx(200.0)


def test_interval_rejects_unexplained_energy_creation() -> None:
    with pytest.raises(ValueError, match="storage conservation"):
        _interval(storage_energy_at_end_wh=2300.0)


def test_pv_only_policy_rejects_grid_to_storage() -> None:
    with pytest.raises(ValueError, match="does not permit grid-to-storage"):
        _interval(charge_source_policy=ChargeSourcePolicy.PV_ONLY)


def test_household_only_policy_rejects_storage_export() -> None:
    with pytest.raises(ValueError, match="does not permit storage-to-grid"):
        _interval(
            storage_to_grid_output_wh=50.0,
            storage_to_household_output_wh=100.0,
        )


def test_ledger_requires_contiguous_intervals_and_matching_lineage() -> None:
    first = _interval()
    second = _interval(
        starts_at=first.ends_at,
        ends_at=first.ends_at + timedelta(minutes=15),
        storage_energy_at_start_wh=first.storage_energy_at_end_wh,
        storage_energy_at_end_wh=2500.0,
    )
    ledger = HouseholdEnergyLedger(
        ledger_id="ledger-1",
        run_id="run-1",
        snapshot_id="snapshot-1",
        candidate_id="candidate-1",
        energy_path_id="energy-path-1",
        horizon_start=first.starts_at,
        horizon_end=second.ends_at,
        intervals=(first, second),
        method_version="canonical-household-energy-ledger:v1",
    )

    assert ledger.intervals == (first, second)
    with pytest.raises(ValueError, match="contiguous"):
        HouseholdEnergyLedger(
            ledger_id="ledger-gap",
            run_id="run-1",
            snapshot_id="snapshot-1",
            candidate_id="candidate-1",
            energy_path_id="energy-path-1",
            horizon_start=first.starts_at,
            horizon_end=second.ends_at + timedelta(minutes=15),
            intervals=(
                first,
                _interval(
                    starts_at=first.ends_at + timedelta(minutes=15),
                    ends_at=first.ends_at + timedelta(minutes=30),
                ),
            ),
            method_version="canonical-household-energy-ledger:v1",
        )


def test_energy_contract_preserves_components_without_combining_them() -> None:
    interval = EnergyTariffInterval(
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=15),
        commodity_import_eur_per_kwh=0.10,
        commodity_export_eur_per_kwh=0.08,
        supplier_import_eur_per_kwh=0.02,
        supplier_export_eur_per_kwh=-0.01,
        energy_tax_import_eur_per_kwh=0.12,
        export_charge_eur_per_kwh=0.005,
        transaction_fee_import_eur_per_kwh=0.001,
        transaction_fee_export_eur_per_kwh=0.002,
        vat_rate=0.21,
        price_components_include_vat=False,
        confidence=1.0,
        evidence_ids=("price:q1", "contract:v1"),
    )
    contract = EnergyContractSnapshot(
        contract_snapshot_id="contract-snapshot-1",
        captured_at=BASE,
        valid_from=BASE,
        valid_until=interval.ends_at,
        settlement_timezone="Europe/Amsterdam",
        settlement_rule_id="dynamic-quarter-hour:v1",
        contract_version="energy-contract:v1",
        permits_grid_import=True,
        permits_grid_export=True,
        permits_battery_export=True,
        intervals=(interval,),
    )

    assert contract.intervals[0].commodity_import_eur_per_kwh == pytest.approx(0.10)
    assert contract.intervals[0].energy_tax_import_eur_per_kwh == pytest.approx(0.12)
    with pytest.raises(FrozenInstanceError):
        contract.permits_battery_export = False  # type: ignore[misc]


def test_energy_contract_rejects_overlapping_tariff_intervals() -> None:
    first = EnergyTariffInterval.basic(
        starts_at=BASE,
        ends_at=BASE + timedelta(minutes=15),
        import_eur_per_kwh=0.20,
        export_eur_per_kwh=0.10,
        evidence_ids=("price:1",),
    )
    overlapping = EnergyTariffInterval.basic(
        starts_at=BASE + timedelta(minutes=10),
        ends_at=BASE + timedelta(minutes=25),
        import_eur_per_kwh=0.21,
        export_eur_per_kwh=0.11,
        evidence_ids=("price:2",),
    )

    with pytest.raises(ValueError, match="overlap"):
        EnergyContractSnapshot(
            contract_snapshot_id="contract-overlap",
            captured_at=BASE,
            valid_from=BASE,
            valid_until=overlapping.ends_at,
            settlement_timezone="Europe/Amsterdam",
            settlement_rule_id="dynamic-quarter-hour:v1",
            contract_version="energy-contract:v1",
            permits_grid_import=True,
            permits_grid_export=True,
            permits_battery_export=False,
            intervals=(first, overlapping),
        )


def test_financial_outcome_validates_complete_net_result() -> None:
    outcome = FinancialSettlementOutcome(
        settlement_id="settlement-1",
        ledger_id="ledger-1",
        contract_snapshot_id="contract-snapshot-1",
        grid_import_energy_wh=1000.0,
        grid_export_energy_wh=500.0,
        grid_import_cost_eur=0.25,
        grid_export_value_eur=0.10,
        avoided_import_value_eur=0.20,
        variable_charges_eur=0.02,
        storage_conversion_loss_cost_eur=0.03,
        battery_use_cost_eur=0.01,
        minimum_profit_margin_eur=0.04,
        net_financial_result_eur=0.02,
        confidence=0.9,
        settlement_method_version="energy-contract-settlement:v1",
        evidence_ids=("ledger-1", "contract-snapshot-1"),
    )

    assert outcome.gross_market_benefit_eur == pytest.approx(0.30)
    assert outcome.total_variable_cost_eur == pytest.approx(0.28)
    assert outcome.minimum_margin_satisfied is False

    with pytest.raises(ValueError, match="net financial result"):
        FinancialSettlementOutcome(
            settlement_id="settlement-invalid",
            ledger_id="ledger-1",
            contract_snapshot_id="contract-snapshot-1",
            grid_import_energy_wh=1000.0,
            grid_export_energy_wh=500.0,
            grid_import_cost_eur=0.25,
            grid_export_value_eur=0.10,
            avoided_import_value_eur=0.20,
            variable_charges_eur=0.02,
            storage_conversion_loss_cost_eur=0.03,
            battery_use_cost_eur=0.01,
            minimum_profit_margin_eur=0.04,
            net_financial_result_eur=0.50,
            confidence=0.9,
            settlement_method_version="energy-contract-settlement:v1",
            evidence_ids=("ledger-1", "contract-snapshot-1"),
        )


def test_canonical_settlement_values_ledger_flows_once_per_interval() -> None:
    physical = _interval()
    ledger = HouseholdEnergyLedger(
        ledger_id="ledger-settlement",
        run_id="run-1",
        snapshot_id="snapshot-1",
        candidate_id="candidate-1",
        energy_path_id="energy-path-1",
        horizon_start=physical.starts_at,
        horizon_end=physical.ends_at,
        intervals=(physical,),
        method_version="canonical-household-energy-ledger:v1",
    )
    tariff = EnergyTariffInterval(
        starts_at=physical.starts_at,
        ends_at=physical.ends_at,
        commodity_import_eur_per_kwh=0.10,
        commodity_export_eur_per_kwh=0.08,
        supplier_import_eur_per_kwh=0.02,
        supplier_export_eur_per_kwh=-0.01,
        energy_tax_import_eur_per_kwh=0.12,
        export_charge_eur_per_kwh=0.005,
        transaction_fee_import_eur_per_kwh=0.001,
        transaction_fee_export_eur_per_kwh=0.002,
        vat_rate=0.21,
        price_components_include_vat=False,
        confidence=0.9,
        evidence_ids=("tariff:q1", "contract:v1"),
    )
    contract = EnergyContractSnapshot(
        contract_snapshot_id="contract-settlement",
        captured_at=physical.starts_at,
        valid_from=physical.starts_at,
        valid_until=physical.ends_at,
        settlement_timezone="Europe/Amsterdam",
        settlement_rule_id="dynamic-quarter-hour:v1",
        contract_version="energy-contract:v1",
        permits_grid_import=True,
        permits_grid_export=True,
        permits_battery_export=False,
        intervals=(tariff,),
    )

    settlement = CanonicalFinancialSettlementProducer().settle(
        ledger=ledger,
        contract=contract,
    )

    assert settlement.grid_import_energy_wh == pytest.approx(350.0)
    assert settlement.grid_export_energy_wh == pytest.approx(200.0)
    assert settlement.grid_import_cost_eur == pytest.approx(0.09317)
    assert settlement.grid_export_value_eur == pytest.approx(0.01694)
    assert settlement.avoided_import_value_eur == pytest.approx(0.0437415)
    assert settlement.variable_charges_eur == pytest.approx(0.0105875)
    assert settlement.foregone_export_result_eur == pytest.approx(0.030492)
    assert settlement.storage_conversion_loss_cost_eur == pytest.approx(0.0205458)
    assert settlement.net_financial_result_eur == pytest.approx(-0.073568)
    assert settlement.confidence == pytest.approx(0.8)
    assert len(settlement.intervals) == 1
    # Conversion-loss cost is an attributable subset of purchased/foregone energy,
    # not a second debit in the net result.
    assert settlement.total_variable_cost_eur == pytest.approx(
        settlement.grid_import_cost_eur
        + settlement.variable_charges_eur
        + settlement.foregone_export_result_eur
    )


def test_canonical_settlement_preserves_negative_dynamic_price_result() -> None:
    physical = _interval(
        household_demand_wh=100.0,
        usable_pv_wh=0.0,
        pv_to_household_wh=0.0,
        pv_to_storage_input_wh=0.0,
        pv_to_grid_wh=0.0,
        curtailed_pv_wh=0.0,
        grid_to_household_wh=100.0,
        grid_to_storage_input_wh=0.0,
        storage_to_household_output_wh=0.0,
        storage_charge_loss_wh=0.0,
        storage_discharge_loss_wh=0.0,
        storage_energy_at_end_wh=2000.0,
        charge_source_policy=None,
        discharge_destination_policy=None,
    )
    ledger = HouseholdEnergyLedger(
        ledger_id="ledger-negative-price",
        run_id="run-1",
        snapshot_id="snapshot-1",
        candidate_id="candidate-1",
        energy_path_id="energy-path-1",
        horizon_start=physical.starts_at,
        horizon_end=physical.ends_at,
        intervals=(physical,),
        method_version="canonical-household-energy-ledger:v1",
    )
    tariff = EnergyTariffInterval.basic(
        starts_at=physical.starts_at,
        ends_at=physical.ends_at,
        import_eur_per_kwh=-0.10,
        export_eur_per_kwh=-0.05,
        evidence_ids=("negative-price:q1",),
    )
    contract = EnergyContractSnapshot(
        contract_snapshot_id="contract-negative-price",
        captured_at=physical.starts_at,
        valid_from=physical.starts_at,
        valid_until=physical.ends_at,
        settlement_timezone="Europe/Amsterdam",
        settlement_rule_id="dynamic-quarter-hour:v1",
        contract_version="energy-contract:v1",
        permits_grid_import=True,
        permits_grid_export=True,
        permits_battery_export=False,
        intervals=(tariff,),
    )

    settlement = CanonicalFinancialSettlementProducer().settle(
        ledger=ledger,
        contract=contract,
    )

    assert settlement.grid_import_cost_eur == pytest.approx(-0.01)
    assert settlement.net_financial_result_eur == pytest.approx(0.01)


def test_canonical_settlement_fails_closed_without_exact_tariff_interval() -> None:
    physical = _interval()
    ledger = HouseholdEnergyLedger(
        ledger_id="ledger-misaligned",
        run_id="run-1",
        snapshot_id="snapshot-1",
        candidate_id="candidate-1",
        energy_path_id="energy-path-1",
        horizon_start=physical.starts_at,
        horizon_end=physical.ends_at,
        intervals=(physical,),
        method_version="canonical-household-energy-ledger:v1",
    )
    shifted = EnergyTariffInterval.basic(
        starts_at=physical.starts_at + timedelta(minutes=5),
        ends_at=physical.ends_at,
        import_eur_per_kwh=0.20,
        export_eur_per_kwh=0.10,
        evidence_ids=("shifted-price:q1",),
    )
    contract = EnergyContractSnapshot(
        contract_snapshot_id="contract-misaligned",
        captured_at=physical.starts_at,
        valid_from=physical.starts_at,
        valid_until=physical.ends_at,
        settlement_timezone="Europe/Amsterdam",
        settlement_rule_id="dynamic-quarter-hour:v1",
        contract_version="energy-contract:v1",
        permits_grid_import=True,
        permits_grid_export=True,
        permits_battery_export=False,
        intervals=(shifted,),
    )

    with pytest.raises(ValueError, match="exact tariff evidence"):
        CanonicalFinancialSettlementProducer().settle(
            ledger=ledger,
            contract=contract,
        )
