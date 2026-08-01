from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.household_state import HouseholdState, Phase, PhaseState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=2,
        source_profile_version=4,
        mapping_version="objective-map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def _versions() -> PlanningInputVersions:
    return PlanningInputVersions(
        capability_mapping=3,
        user_rules=5,
        commitments=2,
        household_state=11,
        forecasts=7,
    )


def _household_state(measured_at: datetime) -> HouseholdState:
    return HouseholdState(
        measured_at=measured_at,
        phases=(
            PhaseState(
                phase=Phase.L1,
                current_a=8.0,
                voltage_v=236.0,
                active_power_w=1888.0,
                main_fuse_limit_a=25.0,
                operational_margin_a=2.0,
            ),
        ),
        grid_power_w=900.0,
        pv_power_w=2500.0,
        household_load_w=3400.0,
    )


def _snapshot() -> PlanningInputSnapshot:
    captured_at = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
    return PlanningInputSnapshot(
        snapshot_id="snapshot-0001",
        captured_at=captured_at,
        horizon_end=captured_at + timedelta(hours=36),
        strategy=_strategy(),
        household_state=_household_state(captured_at),
        runtime_state=RuntimePressureState.NORMAL,
        versions=_versions(),
        replan_reasons=("initial_planner_run",),
    )


def test_snapshot_is_immutable() -> None:
    snapshot = _snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.snapshot_id = "changed"  # type: ignore[misc]


def test_snapshot_preserves_exact_strategy_versions_and_household_state() -> None:
    snapshot = _snapshot()

    assert snapshot.strategy.strategy_version == 2
    assert snapshot.strategy.mapping_version == "objective-map-v1"
    assert snapshot.versions.household_state == 11
    assert snapshot.household_state.phases[0].phase is Phase.L1
    assert snapshot.runtime_state is RuntimePressureState.NORMAL


def test_snapshot_rejects_naive_capture_time() -> None:
    captured_at = datetime(2026, 8, 1, 18, 0)

    with pytest.raises(ValueError, match="capture time must be timezone-aware"):
        PlanningInputSnapshot(
            snapshot_id="snapshot-0002",
            captured_at=captured_at,
            horizon_end=datetime(2026, 8, 3, 6, 0, tzinfo=UTC),
            strategy=_strategy(),
            household_state=_household_state(datetime(2026, 8, 1, 18, 0, tzinfo=UTC)),
            runtime_state=RuntimePressureState.NORMAL,
            versions=_versions(),
            replan_reasons=("forecast_changed",),
        )


def test_snapshot_rejects_non_future_horizon() -> None:
    captured_at = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="must end after"):
        PlanningInputSnapshot(
            snapshot_id="snapshot-0003",
            captured_at=captured_at,
            horizon_end=captured_at,
            strategy=_strategy(),
            household_state=_household_state(captured_at),
            runtime_state=RuntimePressureState.NORMAL,
            versions=_versions(),
            replan_reasons=("user_rules_changed",),
        )


def test_snapshot_requires_explicit_replan_reason() -> None:
    captured_at = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="requires a replan reason"):
        PlanningInputSnapshot(
            snapshot_id="snapshot-0004",
            captured_at=captured_at,
            horizon_end=captured_at + timedelta(hours=36),
            strategy=_strategy(),
            household_state=_household_state(captured_at),
            runtime_state=RuntimePressureState.TRANSIENT_PRESSURE,
            versions=_versions(),
            replan_reasons=(),
        )


def test_snapshot_rejects_future_household_measurement() -> None:
    captured_at = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="cannot be measured after"):
        PlanningInputSnapshot(
            snapshot_id="snapshot-0005",
            captured_at=captured_at,
            horizon_end=captured_at + timedelta(hours=36),
            strategy=_strategy(),
            household_state=_household_state(captured_at + timedelta(seconds=1)),
            runtime_state=RuntimePressureState.NORMAL,
            versions=_versions(),
            replan_reasons=("measurement_changed",),
        )


def test_input_versions_reject_zero_or_negative_values() -> None:
    with pytest.raises(ValueError, match="forecasts version must be at least 1"):
        PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=0,
        )
