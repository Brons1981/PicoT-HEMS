from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from test_independent_daily_simulator import _household, _storage, _timeline

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.independent_daily_intent_simulator import (
    IndependentDailyIntentSimulator,
)


def _discover(
    *,
    soc: float = 0.5,
    deplete_after_pv: bool = False,
    micro_charge_suppression_fraction: float = 0.01,
    charge_session_active: bool = False,
    required_by=None,
):
    scenarios = tuple(_timeline(scenario) for scenario in PVScenario)
    if deplete_after_pv:
        scenarios = tuple(
            replace(
                scenario,
                timeline=replace(
                    scenario.timeline,
                    intervals=tuple(
                        replace(interval, energy_wh=0.0)
                        if index >= 3
                        else interval
                        for index, interval in enumerate(
                            scenario.timeline.intervals
                        )
                    ),
                ),
            )
            for scenario in scenarios
        )
    return IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-intent",
        household=_household(),
        pv_scenarios=scenarios,
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
        micro_charge_suppression_fraction=micro_charge_suppression_fraction,
        charge_session_active=charge_session_active,
        required_by=required_by,
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


def test_discoverer_can_start_now_inside_an_already_running_quarter() -> None:
    original_household = _household()
    captured_at = original_household.horizon_start + timedelta(minutes=7)
    household = replace(
        original_household,
        created_at=captured_at,
        horizon_start=captured_at,
        intervals=(
            replace(original_household.intervals[0], starts_at=captured_at),
            *original_household.intervals[1:],
        ),
    )
    scenarios = tuple(
        replace(
            item,
            timeline=replace(
                item.timeline,
                created_at=captured_at,
                horizon_start=captured_at,
                intervals=(
                    replace(item.timeline.intervals[0], starts_at=captured_at),
                    *item.timeline.intervals[1:],
                ),
            ),
        )
        for item in (_timeline(scenario) for scenario in PVScenario)
    )

    result = IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-running-window",
        household=household,
        pv_scenarios=scenarios,
        storage_state=replace(_storage(0.5), measured_at=captured_at),
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

    immediate = tuple(
        window for window in result.windows if window.starts_at == captured_at
    )
    assert immediate
    assert all(
        window.schedule.intervals[0].intent is window.intent
        for window in immediate
    )
    assert all(window.ends_at.second == 0 for window in immediate)
    assert all(window.ends_at.minute % 15 == 0 for window in immediate)


def test_discoverer_recovers_target_after_full_storage_is_later_depleted() -> None:
    result = _discover(soc=1.0, deplete_after_pv=True)

    assert result.windows
    assert all(
        item.conservative_target_reached_at > item.starts_at
        for item in result.windows
    )


def test_configured_two_percent_gap_does_not_create_a_new_charge_window() -> None:
    result = _discover(
        soc=0.98,
        micro_charge_suppression_fraction=0.02,
    )

    assert result.discovery_status == "not_required"
    assert result.windows == ()


def test_configured_limit_does_not_interrupt_an_active_charge_session() -> None:
    result = _discover(
        soc=0.98,
        micro_charge_suppression_fraction=0.02,
        charge_session_active=True,
    )

    assert result.discovery_status == "discovered"
    assert result.windows


def test_discoverer_does_not_import_current_pipeline_selection_types() -> None:
    from picot.planner import independent_daily_charge_window_discoverer as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names


def test_discoverer_excludes_windows_that_miss_required_by() -> None:
    required_by = _household().horizon_start + timedelta(minutes=90)

    # At 75% SoC the physical target is reachable before this deadline, while
    # later start alternatives still exist and must be excluded.
    result = _discover(soc=0.75, required_by=required_by)

    assert result.windows
    assert all(item.ends_at <= required_by for item in result.windows)
    assert all(
        item.conservative_target_reached_at <= required_by
        for item in result.windows
    )


def test_discoverer_builds_pv_first_hybrid_with_only_residual_grid_recovery() -> None:
    """Low PV must remain useful before a minimal conservative grid recovery."""

    household = _household()
    scenarios = tuple(
        replace(
            source,
            timeline=replace(
                source.timeline,
                intervals=tuple(
                    replace(
                        interval,
                        energy_wh=(
                            {
                                PVScenario.LOWER: 250.0,
                                PVScenario.CENTRAL: 300.0,
                                PVScenario.UPPER: 350.0,
                            }[source.scenario]
                            if index < 3
                            else 0.0
                        ),
                    )
                    for index, interval in enumerate(source.timeline.intervals)
                ),
            ),
        )
        for source in (_timeline(scenario) for scenario in PVScenario)
    )
    conversion = StorageConversionModel(
        model_id="conversion",
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        evidence_ids=("conversion",),
        method_version="test:v1",
    )

    result = IndependentDailyChargeWindowDiscoverer().discover(
        snapshot_id="snapshot-hybrid",
        household=household,
        pv_scenarios=scenarios,
        storage_state=_storage(0.5),
        conversion_model=conversion,
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )

    hybrid = next(
        schedule
        for schedule in result.hybrid_schedules
        if DailyStorageIntent.NOM
        in {interval.intent for interval in schedule.intervals}
        and DailyStorageIntent.GRID_REQUIREMENT
        in {interval.intent for interval in schedule.intervals}
        and next(
            interval.starts_at
            for interval in schedule.intervals
            if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
        )
        >= household.intervals[3].starts_at
    )
    intents = tuple(interval.intent for interval in hybrid.intervals)
    assert intents[:3] == (DailyStorageIntent.NOM,) * 3

    simulation = IndependentDailyIntentSimulator().simulate(
        snapshot_id="snapshot-hybrid",
        household=household,
        pv_scenarios=scenarios,
        storage_state=_storage(0.5),
        conversion_model=conversion,
        intent_schedule=hybrid,
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )
    assert all(item.target_reached_at is not None for item in simulation.trajectories)
    assert {
        trajectory.scenario: sum(
            interval.grid_to_storage_input_wh
            for interval in trajectory.intervals
        )
        for trajectory in simulation.trajectories
    } == {
        PVScenario.LOWER: 3630.0,
        PVScenario.CENTRAL: 3480.0,
        PVScenario.UPPER: 3330.0,
    }
