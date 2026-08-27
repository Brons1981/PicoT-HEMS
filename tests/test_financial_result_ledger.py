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
    assert today["household_energy_sources"] == {
        "household_load_kwh": 1.0,
        "sources": [
            {
                "source": "pv_direct",
                "energy_kwh": 0.0,
                "share": 0.0,
                "value_eur": 0.0,
                "value_kind": "avoided_grid_import",
            },
            {
                "source": "battery",
                "energy_kwh": 1.0,
                "share": 1.0,
                "value_eur": 0.25,
                "value_kind": "avoided_grid_import_gross",
            },
            {
                "source": "grid",
                "energy_kwh": 0.0,
                "share": 0.0,
                "value_eur": 0.0,
                "value_kind": "energy_cost",
            },
        ],
    }


def test_household_energy_sources_reconcile_energy_and_source_value(tmp_path) -> None:
    view = _ledger(tmp_path).update(
        _snapshot(price=0.25),
        _history(
            pv_generation=500.0,
            household_load=1000.0,
            grid_import=250.0,
            grid_export=0.0,
            battery_charge=0.0,
            battery_discharge=250.0,
        ),
    )

    today = view["today"]
    assert isinstance(today, dict)
    breakdown = today["household_energy_sources"]
    assert isinstance(breakdown, dict)
    assert breakdown["household_load_kwh"] == pytest.approx(1.0)
    sources = {item["source"]: item for item in breakdown["sources"]}
    assert sources["pv_direct"]["energy_kwh"] == pytest.approx(0.5)
    assert sources["battery"]["energy_kwh"] == pytest.approx(0.25)
    assert sources["grid"]["energy_kwh"] == pytest.approx(0.25)
    assert sum(item["share"] for item in sources.values()) == pytest.approx(1.0)
    assert sources["pv_direct"]["value_eur"] == pytest.approx(0.125)
    assert sources["battery"]["value_eur"] == pytest.approx(0.0625)
    assert sources["grid"]["value_eur"] == pytest.approx(0.0625)


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
    assert view["today"]["coverage_by_role"]["battery_charge"][
        "start_anchor_available"
    ] is True


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


def test_storage_inventory_values_pv_at_foregone_export_revenue(tmp_path) -> None:
    snapshot = replace(
        _snapshot(price=0.10),
        current_storage_states=(
            replace(_snapshot().current_storage_states[0], current_soc=0.25),
        ),
    )
    ledger = _ledger(tmp_path)

    ledger.update(
        snapshot,
        _history(
            pv_generation=2000.0,
            household_load=0.0,
            grid_import=0.0,
            grid_export=1000.0,
            battery_charge=1000.0,
            battery_discharge=0.0,
        ),
    )

    inventory = ledger.storage_energy_inventory()
    assert inventory is not None
    pv_lot = next(item for item in inventory.lots if item.source == "pv")
    assert pv_lot.stored_energy_wh == pytest.approx(1000.0)
    assert pv_lot.acquisition_cost_eur == pytest.approx(0.10)
    assert inventory.measured_stored_energy_wh == pytest.approx(2040.0)


def test_storage_inventory_keeps_unproven_opening_energy_unknown(tmp_path) -> None:
    ledger = _ledger(tmp_path)
    ledger.update(
        _snapshot(),
        _history(
            pv_generation=0.0,
            household_load=0.0,
            grid_import=0.0,
            grid_export=0.0,
            battery_charge=0.0,
            battery_discharge=0.0,
        ),
    )

    inventory = ledger.storage_energy_inventory()
    assert inventory is not None
    assert inventory.known_stored_energy_wh == pytest.approx(0.0)
    assert inventory.lots[0].source == "unknown"
    assert inventory.lots[0].acquisition_cost_eur is None


def test_storage_inventory_cost_basis_survives_the_day_boundary(tmp_path) -> None:
    ledger = _ledger(tmp_path)
    first = replace(
        _snapshot(price=0.10),
        current_storage_states=(
            replace(_snapshot().current_storage_states[0], current_soc=0.25),
        ),
    )
    ledger.update(
        first,
        _history(
            pv_generation=2000.0,
            household_load=0.0,
            grid_import=0.0,
            grid_export=1000.0,
            battery_charge=1000.0,
            battery_discharge=0.0,
        ),
    )
    shift = timedelta(days=1)
    second = replace(
        first,
        captured_at=first.captured_at + shift,
        horizon_end=first.horizon_end + shift,
        price_points=tuple(
            replace(
                item,
                starts_at=item.starts_at + shift,
                ends_at=item.ends_at + shift,
            )
            for item in first.price_points
        ),
        current_storage_states=tuple(
            replace(item, measured_at=item.measured_at + shift)
            for item in first.current_storage_states
        ),
    )
    first_history = _history(
        pv_generation=0.0,
        household_load=0.0,
        grid_import=0.0,
        grid_export=0.0,
        battery_charge=0.0,
        battery_discharge=0.0,
    )
    second_history = replace(
        first_history,
        starts_at=first_history.starts_at + shift,
        ends_at=first_history.ends_at + shift,
        series=tuple(
            replace(
                series,
                points=tuple(
                    replace(point, sampled_at=point.sampled_at + shift)
                    for point in series.points
                ),
            )
            for series in first_history.series
        ),
    )

    ledger.update(second, second_history)

    inventory = ledger.storage_energy_inventory()
    assert inventory is not None
    pv_lot = next(item for item in inventory.lots if item.source == "pv")
    assert pv_lot.stored_energy_wh == pytest.approx(1000.0)
    assert pv_lot.acquisition_cost_eur == pytest.approx(0.10)
