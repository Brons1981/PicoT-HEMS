from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    CurrentStorageState,
    PlanningInputSnapshot,
    PriceForecastPoint,
    StoragePhysicalLimits,
)
from picot.v2.financial_result_ledger import FinancialResultLedger
from picot.v2.power_history import (
    PowerHistoryPoint,
    PowerHistorySeries,
    PowerHistorySnapshot,
)


def _snapshot(*, price: float = 0.25) -> PlanningInputSnapshot:
    start = datetime(2026, 8, 27, 10, tzinfo=UTC)
    end = start + timedelta(hours=1)
    return PlanningInputSnapshot(
        run_id="run",
        snapshot_id="snapshot",
        captured_at=end,
        picot_version="test",
        architecture_baseline_commit="baseline",
        pipeline_contract_version=2,
        strategy_id="strategy",
        horizon_end=end + timedelta(hours=1),
        price_points=(
            PriceForecastPoint(
                point_id="price",
                starts_at=start,
                ends_at=end,
                value_eur_per_kwh=price,
                confidence=1.0,
                evidence_id="price-evidence",
            ),
        ),
        current_storage_states=(
            CurrentStorageState(
                storage_state_id="storage",
                execution_scope_id="battery",
                capability_id="capability",
                current_soc=0.5,
                usable_capacity_wh=8160.0,
                measured_at=end,
                confidence=1.0,
                evidence_ids=("soc",),
            ),
        ),
        storage_physical_limits=(
            StoragePhysicalLimits(
                execution_scope_id="battery",
                capability_id="capability",
                minimum_soc=0.1,
                maximum_soc=1.0,
                maximum_charge_input_power_w=2400.0,
                maximum_discharge_output_power_w=2400.0,
                evidence_ids=("limits",),
                method_version="test",
            ),
        ),
    )


def _history(**powers: float) -> PowerHistorySnapshot:
    start = datetime(2026, 8, 27, 10, tzinfo=UTC)
    end = start + timedelta(hours=1)
    return PowerHistorySnapshot(
        starts_at=start,
        ends_at=end,
        status="available",
        error=None,
        series=tuple(
            PowerHistorySeries(
                series_id=role,
                role=role,
                source_entity_id=f"sensor.{role}",
                transform="positive",
                points=(
                    PowerHistoryPoint(start, power, f"{role}-start"),
                    PowerHistoryPoint(end, power, f"{role}-end"),
                ),
            )
            for role, power in powers.items()
        ),
    )


def _ledger(tmp_path) -> FinancialResultLedger:
    return FinancialResultLedger(
        state_path=tmp_path / "financial.json",
        wear_eur_per_discharge_kwh=0.05,
        battery_purchase_eur=2407.40,
    )


def test_normal_self_consumption_is_battery_value_but_not_picot_value(tmp_path) -> None:
    view = _ledger(tmp_path).update(
        _snapshot(),
        _history(
            pv_generation=0.0,
            household_load=1000.0,
            grid_import=0.0,
            grid_export=0.0,
            battery_charge=0.0,
            battery_discharge=1000.0,
        ),
    )

    today = view["today"]
    assert isinstance(today, dict)
    assert today["gross_battery_value_eur"] == pytest.approx(0.25)
    assert today["grid_import_cost_eur"] == pytest.approx(0.0)
    assert today["grid_export_revenue_eur"] == pytest.approx(0.0)
    assert today["net_total_energy_value_eur"] == pytest.approx(0.20)
    assert today["battery_wear_eur"] == pytest.approx(0.05)
    assert today["net_battery_value_eur"] == pytest.approx(0.20)
    assert today["net_picot_value_eur"] == pytest.approx(0.0)


def test_profitable_picot_export_is_net_of_incremental_wear(tmp_path) -> None:
    view = _ledger(tmp_path).update(
        _snapshot(price=0.30),
        _history(
            pv_generation=0.0,
            household_load=0.0,
            grid_import=0.0,
            grid_export=1000.0,
            battery_charge=0.0,
            battery_discharge=1000.0,
        ),
    )

    today = view["today"]
    assert isinstance(today, dict)
    assert today["gross_picot_value_eur"] == pytest.approx(0.30)
    assert today["grid_export_revenue_eur"] == pytest.approx(0.30)
    assert today["net_picot_value_eur"] == pytest.approx(0.25)
    assert view["cumulative"]["net_picot_value_eur"] == pytest.approx(0.25)


def test_missing_measured_role_never_produces_estimated_money(tmp_path) -> None:
    history = _history(
        pv_generation=0.0,
        household_load=1000.0,
        grid_import=0.0,
        grid_export=0.0,
        battery_charge=0.0,
    )

    view = _ledger(tmp_path).update(_snapshot(), history)

    assert view["status"] == "incomplete"
    assert view["today"]["reason"] == "missing_measured_series"
    assert view["today"]["missing_roles"] == ["battery_discharge"]


def test_dashboard_contract_is_passive_and_persists_purchase_progress(tmp_path) -> None:
    path = tmp_path / "financial.json"
    ledger = FinancialResultLedger(state_path=path)
    ledger.update(
        _snapshot(),
        _history(
            pv_generation=0.0,
            household_load=1000.0,
            grid_import=0.0,
            grid_export=0.0,
            battery_charge=0.0,
            battery_discharge=1000.0,
        ),
    )

    restored = FinancialResultLedger(state_path=path).dashboard_view()

    assert restored["observer_only"] is True
    assert restored["selection_permitted"] is False
    assert restored["commitment_permitted"] is False
    assert restored["cumulative"]["battery_purchase_eur"] == 2407.40
    assert restored["cumulative"]["net_battery_value_eur"] == pytest.approx(0.20)


def test_full_source_prices_cover_history_removed_from_planning_snapshot(tmp_path) -> None:
    snapshot = _snapshot()
    history = _history(
        pv_generation=0.0,
        household_load=1000.0,
        grid_import=1000.0,
        grid_export=0.0,
        battery_charge=0.0,
        battery_discharge=0.0,
    )
    future_only_snapshot = replace(snapshot, price_points=())

    without_source_prices = _ledger(tmp_path).update(
        future_only_snapshot,
        history,
    )
    with_source_prices = _ledger(tmp_path).update(
        future_only_snapshot,
        history,
        price_points=snapshot.price_points,
    )

    assert without_source_prices["status"] == "incomplete"
    assert without_source_prices["today"]["reason"] == "price_coverage_incomplete"
    assert with_source_prices["status"] == "available"
    assert with_source_prices["today"]["grid_import_cost_eur"] == pytest.approx(0.25)
