from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.addon.planning_snapshot_assembly import (
    NormalizedPlanningInputs,
    assemble_planning_input_snapshot,
)
from picot.adapters.home_assistant_household_state import household_state_from_grid_power_entity
from picot.domain.forecast import ForecastSet
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import PlanningInputVersions


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def _versions() -> PlanningInputVersions:
    return PlanningInputVersions(
        capability_mapping=1,
        user_rules=1,
        commitments=1,
        household_state=1,
        forecasts=1,
    )


def test_direct_ha_source_is_normalized_then_frozen_into_snapshot() -> None:
    source_state = {
        "entity_id": "sensor.shellypro3em_5c013b04bb78_vermogen",
        "state": "842.5",
        "last_updated": "2026-08-12T10:00:00+00:00",
        "attributes": {"unit_of_measurement": "W"},
    }
    household_state = household_state_from_grid_power_entity(source_state)
    captured_at = datetime(2026, 8, 12, 10, 0, 1, tzinfo=UTC)

    snapshot = assemble_planning_input_snapshot(
        snapshot_id="live-0001",
        captured_at=captured_at,
        horizon_end=captured_at + timedelta(hours=24),
        strategy=_strategy(),
        inputs=NormalizedPlanningInputs(
            household_state=household_state,
            forecasts=ForecastSet(series=()),
        ),
        versions=_versions(),
        replan_reasons=("live_observation",),
    )

    assert snapshot.household_state.grid_power_w == 842.5
    assert snapshot.household_state.measured_at == datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    assert not hasattr(snapshot.household_state, "entity_id")
    assert "shelly" not in repr(snapshot).lower()


def test_snapshot_assembly_rejects_observation_from_the_future() -> None:
    source_state = {
        "entity_id": "sensor.real_grid_power",
        "state": "100",
        "last_updated": "2026-08-12T10:00:05+00:00",
        "attributes": {"unit_of_measurement": "W"},
    }
    household_state = household_state_from_grid_power_entity(source_state)
    captured_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="measured after snapshot capture time"):
        assemble_planning_input_snapshot(
            snapshot_id="live-0002",
            captured_at=captured_at,
            horizon_end=captured_at + timedelta(hours=24),
            strategy=_strategy(),
            inputs=NormalizedPlanningInputs(
                household_state=household_state,
                forecasts=ForecastSet(series=()),
            ),
            versions=_versions(),
            replan_reasons=("live_observation",),
        )
