from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="objective-map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def _state(state_id: str = "state-1", scope_id: str = "battery-1") -> CurrentStorageState:
    return CurrentStorageState(
        storage_state_id=state_id,
        execution_scope_id=scope_id,
        capability_id="storage-capability-1",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=datetime(2026, 8, 12, 7, 59, tzinfo=UTC),
        confidence=0.99,
        evidence_ids=("sensor:soc", "config:capacity"),
    )


def _snapshot(states: tuple[CurrentStorageState, ...]) -> PlanningInputSnapshot:
    captured_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    return PlanningInputSnapshot(
        snapshot_id="snapshot-adr038",
        captured_at=captured_at,
        horizon_end=captured_at + timedelta(hours=36),
        strategy=_strategy(),
        household_state=HouseholdState(measured_at=captured_at, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(1, 1, 1, 1, 1),
        replan_reasons=("initial_planner_run",),
        current_storage_states=states,
    )


def test_snapshot_accepts_one_immutable_storage_truth_per_scope() -> None:
    state = _state()
    snapshot = _snapshot((state,))

    assert snapshot.current_storage_states == (state,)
    assert snapshot.current_storage_states[0].current_stored_energy_wh == 4000.0


def test_snapshot_accepts_no_storage_state() -> None:
    assert _snapshot(()).current_storage_states == ()


def test_snapshot_rejects_duplicate_storage_state_id() -> None:
    with pytest.raises(ValueError, match="state ID"):
        _snapshot((_state(), _state(scope_id="battery-2")))


def test_snapshot_rejects_duplicate_storage_execution_scope() -> None:
    with pytest.raises(ValueError, match="execution scope"):
        _snapshot((_state(), _state(state_id="state-2")))


def test_snapshot_rejects_storage_measurement_from_future() -> None:
    state = CurrentStorageState(
        storage_state_id="state-future",
        execution_scope_id="battery-1",
        capability_id="storage-capability-1",
        current_soc=0.5,
        usable_capacity_wh=8000.0,
        measured_at=datetime(2026, 8, 12, 8, 1, tzinfo=UTC),
        confidence=0.99,
        evidence_ids=("sensor:soc",),
    )

    with pytest.raises(ValueError, match="after snapshot capture time"):
        _snapshot((state,))
