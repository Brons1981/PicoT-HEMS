from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="objective-map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def _timeline(start: datetime, end: datetime, created_at: datetime | None = None) -> PVEnergyTimeline:
    return PVEnergyTimeline(
        timeline_id="pv-timeline-snapshot",
        created_at=created_at or start,
        horizon_start=start,
        horizon_end=end,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=start,
                ends_at=end,
                energy_wh=1200.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("pv:forecast:v1",),
                method_version="pv-energy-v1",
            ),
        ),
    )


def _snapshot(timeline: PVEnergyTimeline | None) -> PlanningInputSnapshot:
    captured_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    horizon_end = captured_at + timedelta(hours=36)
    return PlanningInputSnapshot(
        snapshot_id="snapshot-adr039",
        captured_at=captured_at,
        horizon_end=horizon_end,
        strategy=_strategy(),
        household_state=HouseholdState(measured_at=captured_at, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(1, 1, 1, 1, 1),
        replan_reasons=("initial_planner_run",),
        pv_energy_timeline=timeline,
    )


def test_snapshot_accepts_matching_pv_energy_timeline() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=36)
    timeline = _timeline(start, end)

    assert _snapshot(timeline).pv_energy_timeline is timeline


def test_snapshot_remains_valid_without_pv_energy_timeline() -> None:
    assert _snapshot(None).pv_energy_timeline is None


def test_snapshot_rejects_pv_timeline_created_after_capture() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=36)
    timeline = _timeline(start, end, created_at=start + timedelta(seconds=1))

    with pytest.raises(ValueError, match="cannot be created after"):
        _snapshot(timeline)


def test_snapshot_rejects_mismatched_pv_timeline_horizon() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    timeline = _timeline(start, start + timedelta(hours=24))

    with pytest.raises(ValueError, match="complete planning horizon"):
        _snapshot(timeline)
