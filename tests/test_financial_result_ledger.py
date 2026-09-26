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
    numeric_power_history,
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


def test_missing_pv_anchor_keeps_independent_grid_results(tmp_path) -> None:
    history = _history(
        pv_generation=0.0, household_load=750.0, grid_import=1000.0,
        grid_export=250.0, battery_charge=0.0, battery_discharge=0.0,
    )
    history = replace(history, series=tuple(
        replace(series, points=series.points[1:])
        if series.role == "pv_generation" else series for series in history.series
    ))
    ledger = _ledger(tmp_path)
    view = ledger.update(_snapshot(), history)

    metrics = view["today"]["financial_metrics"]
    assert metrics["status"] == "partial"
    assert metrics["values"]["grid_import_cost_eur"]["value_eur"] == 0.25
    assert metrics["values"]["grid_export_revenue_eur"]["value_eur"] == 0.0625
    assert metrics["values"]["actual_energy_cost_eur"]["value_eur"] == 0.1875
    assert metrics["values"]["net_battery_value_eur"]["value_eur"] is None
    assert metrics["values"]["net_picot_value_eur"]["value_eur"] is None
    gap = metrics["measurement_coverage"]["pv_generation"]["gaps"][0]
    assert gap["starts_at"] == history.starts_at.isoformat()
    assert gap["ends_at"] == history.ends_at.isoformat()
    assert ledger.storage_energy_inventory() is None
    restored = _ledger(tmp_path).dashboard_view()
    assert restored["today"] == view["today"]
    assert restored["cumulative"]["excluded_battery_days"] == 1


@pytest.mark.parametrize("role", [
    "pv_generation", "household_load", "battery_charge", "battery_discharge",
])
def test_display_gaps_block_benefits_without_changing_inventory(tmp_path, role) -> None:
    history = _history(
        pv_generation=0.0, household_load=1000.0, grid_import=0.0,
        grid_export=0.0, battery_charge=0.0, battery_discharge=1000.0,
    )
    gap_start = history.starts_at + timedelta(minutes=30)
    gap_end = gap_start + timedelta(seconds=70)
    raw = replace(history, series=tuple(
        replace(series, points=(
            series.points[0], PowerHistoryPoint(gap_start, float("nan"), "unavailable"),
            PowerHistoryPoint(gap_end, series.points[0].power_w, "restored"), series.points[-1],
        )) if series.role == role else series for series in history.series
    ))
    numeric = numeric_power_history(raw)
    baseline = _ledger(tmp_path / "baseline")
    baseline_view = baseline.update(_snapshot(), numeric)
    ledger = _ledger(tmp_path / "changed")
    view = ledger.update(_snapshot(), numeric, measurement_history=raw)
    metrics = view["today"]["financial_metrics"]

    assert metrics["values"]["actual_energy_cost_eur"]["value_eur"] == 0.0
    for name in ["net_battery_value_eur", "net_picot_value_eur"]:
        assert metrics["values"][name]["value_eur"] is None
        assert metrics["values"][name]["missing_roles"] == [role]
    assert metrics["measurement_coverage"][role]["gaps"][0]["starts_at"] == gap_start.isoformat()
    assert metrics["measurement_coverage"][role]["gaps"][0]["ends_at"] == gap_end.isoformat()
    assert ledger.storage_energy_inventory() == baseline.storage_energy_inventory()
    assert {k: v for k, v in view["today"].items() if k != "financial_metrics"} == {
        k: v for k, v in baseline_view["today"].items() if k != "financial_metrics"
    }
    assert view["cumulative"]["net_battery_value_eur"] == 0.0
    assert view["cumulative"]["excluded_battery_days"] == 1


def test_missing_export_does_not_hide_measured_import(tmp_path) -> None:
    view = _ledger(tmp_path).update(_snapshot(), _history(grid_import=1000.0))
    metrics = view["today"]["financial_metrics"]["values"]
    assert metrics["grid_import_cost_eur"]["value_eur"] == 0.25
    assert metrics["grid_export_revenue_eur"]["value_eur"] is None
    assert metrics["actual_energy_cost_eur"]["value_eur"] is None


def test_missing_prices_do_not_become_free_energy(tmp_path) -> None:
    view = _ledger(tmp_path).update(_snapshot(), _history(
        grid_import=1000.0, grid_export=0.0, battery_discharge=500.0,
    ), price_points=())
    metrics = view["today"]["financial_metrics"]["values"]
    assert metrics["grid_import_cost_eur"]["value_eur"] is None
    assert metrics["grid_import_cost_eur"]["reason"] == "price_coverage_incomplete"
    assert metrics["grid_export_revenue_eur"]["value_eur"] is None
    assert metrics["battery_wear_eur"]["value_eur"] == 0.025


def test_independent_grid_amounts_follow_price_and_power_boundaries(tmp_path) -> None:
    history = _history(grid_import=1000.0, grid_export=500.0)
    middle = history.starts_at + timedelta(minutes=30)
    history = replace(history, series=tuple(
        replace(series, points=(series.points[0], PowerHistoryPoint(middle, 2000.0, "increase")))
        if series.role == "grid_import" else series for series in history.series
    ))
    original = _snapshot().price_points[0]
    prices = (replace(original, ends_at=middle, value_eur_per_kwh=-0.2),
              replace(original, point_id="later", starts_at=middle, value_eur_per_kwh=0.4))
    values = _ledger(tmp_path).update(
        _snapshot(), history, price_points=prices,
    )["today"]["financial_metrics"]["values"]
    # Import: 0.5 kWh * -0.20 + 1 kWh * 0.40; export: 0.25 kWh at each price.
    assert values["grid_import_cost_eur"]["value_eur"] == 0.3
    assert values["grid_export_revenue_eur"]["value_eur"] == 0.05
    assert values["actual_energy_cost_eur"]["value_eur"] == 0.25


@pytest.mark.parametrize("price", [0.0, -0.2])
def test_zero_and_negative_amounts_are_available_values(tmp_path, price) -> None:
    values = _ledger(tmp_path).update(
        _snapshot(price=price), _history(grid_import=1000.0, grid_export=250.0),
    )["today"]["financial_metrics"]["values"]
    assert values["grid_import_cost_eur"]["status"] == "available"
    assert values["grid_import_cost_eur"]["value_eur"] == price
    assert values["grid_export_revenue_eur"]["value_eur"] == price / 4


@pytest.mark.parametrize("failure", ["read_error", "short_period"])
def test_incomplete_history_read_does_not_claim_current_amounts(tmp_path, failure) -> None:
    history = _history(grid_import=1000.0, grid_export=0.0)
    raw = (replace(history, error="TimeoutError") if failure == "read_error" else
           replace(history, ends_at=history.ends_at - timedelta(minutes=5)))
    values = _ledger(tmp_path).update(
        _snapshot(), history, measurement_history=raw,
    )["today"]["financial_metrics"]["values"]
    assert all(value["value_eur"] is None for value in values.values())


def test_household_sample_gap_does_not_become_a_full_day_value(tmp_path) -> None:
    history = _history(
        pv_generation=0.0, household_load=1000.0, grid_import=1000.0,
        grid_export=0.0, battery_charge=0.0, battery_discharge=0.0,
    )
    history = replace(history, series=tuple(
        replace(series, history_semantics="sampled_linear")
        if series.role == "household_load" else series for series in history.series
    ))
    values = _ledger(tmp_path).update(
        _snapshot(), history,
    )["today"]["financial_metrics"]["values"]
    assert values["actual_energy_cost_eur"]["value_eur"] == 0.25
    assert values["net_picot_value_eur"]["value_eur"] is None
    assert values["net_picot_value_eur"]["missing_roles"] == ["household_load"]


def test_display_assessment_failure_preserves_existing_inventory_update(tmp_path, monkeypatch):
    history = _history(
        pv_generation=0.0, household_load=1000.0, grid_import=0.0,
        grid_export=0.0, battery_charge=0.0, battery_discharge=1000.0,
    )
    baseline = _ledger(tmp_path / "baseline")
    baseline.update(_snapshot(), history)

    def fail(**kwargs):
        raise RuntimeError("injected display failure")

    monkeypatch.setattr("picot.v2.financial_result_ledger.build_financial_metrics", fail)
    ledger = _ledger(tmp_path / "changed")
    view = ledger.update(_snapshot(), history)
    assert view["today"]["financial_metrics"]["reason"] == "financial_metric_evaluation_failed"
    assert view["today"]["financial_metrics"]["error_type"] == "RuntimeError"
    assert view["cumulative"]["excluded_battery_days"] == 1
    assert ledger.storage_energy_inventory() == baseline.storage_energy_inventory()
    assert _ledger(tmp_path / "changed").storage_energy_inventory() == (
        baseline.storage_energy_inventory()
    )


def test_zero_length_day_start_waits_for_a_measured_period(tmp_path):
    history = _history(grid_import=0.0, grid_export=0.0)
    history = replace(history, starts_at=history.ends_at)
    values = _ledger(tmp_path).update(
        _snapshot(), history,
    )["today"]["financial_metrics"]["values"]
    assert all(value["value_eur"] is None for value in values.values())


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
