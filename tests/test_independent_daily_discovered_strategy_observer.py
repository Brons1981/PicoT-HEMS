from __future__ import annotations

from test_independent_daily_reference_portfolio import (
    _tariffs_for_schedule_snapshot,
)
from test_independent_daily_simulator import _household, _storage, _timeline

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.independent_daily_strategy_generator import (
    IndependentDailyStrategyGenerator,
)
from picot.planner.independent_daily_strategy_observer import (
    IndependentDailyStrategyObserver,
)


def _physical_inputs():
    household = _household()
    pv_scenarios = tuple(_timeline(scenario) for scenario in PVScenario)
    storage = _storage(0.5)
    conversion = StorageConversionModel(
        model_id="conversion",
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        evidence_ids=("conversion",),
        method_version="test:v1",
    )
    return household, pv_scenarios, storage, conversion


def test_physical_charge_windows_flow_through_complete_observer_chain() -> None:
    household, pv_scenarios, storage, conversion = _physical_inputs()
    windows = IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-intent",
        household=household,
        pv_scenarios=pv_scenarios,
        storage_state=storage,
        conversion_model=conversion,
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )
    strategy_space = IndependentDailyStrategyGenerator().generate_from_charge_windows(
        charge_windows=windows,
        household=household,
    )
    result = IndependentDailyStrategyObserver().observe(
        strategy_space=strategy_space,
        household=household,
        pv_scenarios=pv_scenarios,
        storage_state=storage,
        conversion_model=conversion,
        tariffs=_tariffs_for_schedule_snapshot(),
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )

    assert strategy_space.source_charge_window_set_id == windows.window_set_id
    assert len(strategy_space.schedules) == (
        len(windows.windows) + len(windows.hybrid_schedules) + 1
    )
    assert all(
        item.intent is DailyStorageIntent.GRID_REQUIREMENT
        for item in windows.windows
    )
    assert all(item.interval_count == 4 for item in windows.windows)
    assert len(result.observer_result.evaluation.records) == len(
        strategy_space.schedules
    )
    assert result.observer_result.best_observation_ids


def test_generator_uses_baseline_when_charge_is_already_not_required() -> None:
    household, pv_scenarios, _storage_state, conversion = _physical_inputs()
    windows = IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-intent",
        household=household,
        pv_scenarios=pv_scenarios,
        storage_state=_storage(1.0),
        conversion_model=conversion,
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )

    strategy_space = IndependentDailyStrategyGenerator().generate_from_charge_windows(
        charge_windows=windows,
        household=household,
    )

    assert windows.discovery_status == "not_required"
    assert strategy_space.charge_requirement_status == "not_required"
    assert strategy_space.active_intents == ()
    assert strategy_space.window_lengths_intervals == ()
    assert len(strategy_space.schedules) == 1
    assert all(
        interval.intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
        for interval in strategy_space.schedules[0].intervals
    )
