from __future__ import annotations

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from test_independent_daily_simulator import _household, _storage, _timeline


def _discover(*, soc: float = 0.5):
    return IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-intent",
        household=_household(),
        pv_scenarios=tuple(_timeline(scenario) for scenario in PVScenario),
        storage_state=_storage(soc),
        conversion_model=StorageConversionModel(
            model_id="conversion",
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            evidence_ids=("conversion",),
            method_version="test:v1",
        ),
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )


def test_discoverer_derives_interval_minimal_charge_windows_from_simulation() -> None:
    result = _discover()

    assert result.windows
    assert {item.intent for item in result.windows}.issubset(
        {DailyStorageIntent.NOM, DailyStorageIntent.GRID_REQUIREMENT}
    )
    assert any(
        item.intent is DailyStorageIntent.GRID_REQUIREMENT
        for item in result.windows
    )
    assert all(item.sufficient_across_scenarios for item in result.windows)
    assert all(not item.one_interval_shorter_sufficient for item in result.windows)
    assert all(
        len(item.scenario_outcomes) == len(PVScenario) for item in result.windows
    )
    assert result.observer_only is True
    assert result.ranking_permitted is False


def test_discovered_window_ends_at_conservative_physical_target_interval() -> None:
    result = _discover()

    for window in result.windows:
        target_interval = next(
            item
            for item in window.schedule.intervals
            if item.starts_at < window.conservative_target_reached_at <= item.ends_at
        )
        assert window.ends_at == target_interval.ends_at


def test_discoverer_creates_no_window_when_storage_is_already_at_target() -> None:
    result = _discover(soc=1.0)

    assert result.windows == ()


def test_discoverer_does_not_import_current_pipeline_selection_types() -> None:
    from picot.planner import independent_daily_charge_window_discoverer as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
