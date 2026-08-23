from __future__ import annotations

import pytest

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import (
    DailyReferenceSimulationSet,
    PVScenario,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_financial_settlement import (
    IndependentDailyFinancialSettlement,
)
from picot.planner.independent_daily_intent_simulator import (
    IndependentDailyIntentSimulator,
)
from test_independent_daily_simulator import (
    _household,
    _storage,
    _timeline,
)


def _schedule(
    intent: DailyStorageIntent,
    *,
    export_target_wh: float = 0.0,
) -> DailyReferenceIntentSchedule:
    household = _household()
    return DailyReferenceIntentSchedule(
        schedule_id=f"schedule-{intent.value}",
        snapshot_id="snapshot-intent",
        horizon_start=household.horizon_start,
        horizon_end=household.horizon_end,
        intervals=tuple(
            DailyReferenceIntentInterval(
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                intent=intent,
                storage_export_target_wh=export_target_wh,
            )
            for item in household.intervals
        ),
        method_version="test:v1",
    )


def _simulate(intent: DailyStorageIntent, *, export_target_wh: float = 0.0):
    return IndependentDailyIntentSimulator().simulate(
        snapshot_id="snapshot-intent",
        household=_household(),
        pv_scenarios=tuple(_timeline(scenario) for scenario in PVScenario),
        storage_state=_storage(0.5),
        conversion_model=StorageConversionModel(
            model_id="conversion",
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            evidence_ids=("conversion",),
            method_version="test:v1",
        ),
        intent_schedule=_schedule(intent, export_target_wh=export_target_wh),
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )


def _tariffs(
    simulation: DailyReferenceSimulationSet,
) -> DailyReferenceTariffSchedule:
    intervals = simulation.trajectories[0].intervals
    return DailyReferenceTariffSchedule(
        schedule_id="intent-tariffs",
        snapshot_id=simulation.snapshot_id,
        horizon_start=intervals[0].starts_at,
        horizon_end=intervals[-1].ends_at,
        intervals=tuple(
            DailyReferenceTariffInterval(
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                import_eur_per_kwh=0.30,
                export_eur_per_kwh=0.10,
                confidence=1.0,
                evidence_ids=(f"tariff-{index}",),
            )
            for index, item in enumerate(intervals)
        ),
        method_version="test:v1",
    )


def test_household_support_discharges_but_never_charges_storage() -> None:
    result = _simulate(DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY)

    for trajectory in result.trajectories:
        assert sum(item.pv_to_storage_input_wh for item in trajectory.intervals) == 0.0
        assert sum(item.grid_to_storage_input_wh for item in trajectory.intervals) == 0.0


def test_standby_keeps_storage_unchanged() -> None:
    result = _simulate(DailyStorageIntent.STANDBY)

    for trajectory in result.trajectories:
        assert all(
            item.storage_energy_at_start_wh == item.storage_energy_at_end_wh
            for item in trajectory.intervals
        )


def test_grid_requirement_uses_pv_first_and_fills_remaining_room_from_grid() -> None:
    result = _simulate(DailyStorageIntent.GRID_REQUIREMENT)

    for trajectory in result.trajectories:
        first = trajectory.intervals[0]
        assert first.pv_to_storage_input_wh > 0.0
        assert first.grid_to_storage_input_wh > 0.0
        assert first.storage_to_household_output_wh == 0.0


def test_storage_export_is_conserved_and_limited_by_reserve() -> None:
    result = _simulate(DailyStorageIntent.STORAGE_EXPORT, export_target_wh=500.0)

    for trajectory in result.trajectories:
        assert sum(item.storage_to_grid_output_wh for item in trajectory.intervals) > 0.0
        assert min(
            item.storage_energy_at_end_wh for item in trajectory.intervals
        ) >= 816.0 - 1e-6


def test_nom_intent_matches_direct_surplus_capture() -> None:
    result = _simulate(DailyStorageIntent.NOM)

    for trajectory in result.trajectories:
        assert trajectory.intervals[0].pv_to_storage_input_wh == pytest.approx(900.0)
        assert trajectory.intervals[0].grid_to_storage_input_wh == 0.0


def test_grid_acquisition_and_storage_export_are_financially_settled() -> None:
    grid = _simulate(DailyStorageIntent.GRID_REQUIREMENT)
    exported = _simulate(DailyStorageIntent.STORAGE_EXPORT, export_target_wh=500.0)

    grid_financial = IndependentDailyFinancialSettlement().settle(
        simulation=grid,
        tariffs=_tariffs(grid),
    )
    export_financial = IndependentDailyFinancialSettlement().settle(
        simulation=exported,
        tariffs=_tariffs(exported),
    )

    assert all(item.grid_import_cost_eur > 0.0 for item in grid_financial.paths)
    assert all(item.grid_export_result_eur > 0.0 for item in export_financial.paths)
