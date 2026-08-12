from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.forecast import ForecastSet
from picot.domain.household_load_forecast import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.domain.storage_energy_requirement import (
    ChargeSourcePolicy,
    StorageEnergyRequirement,
    StorageRequirementReason,
)


def _load_forecast(start: datetime, end: datetime, confidence: float = 0.8) -> HouseholdLoadForecast:
    midpoint = start + (end - start) / 2
    return HouseholdLoadForecast(
        forecast_id="household-load-v1",
        created_at=start - timedelta(minutes=5),
        horizon_start=start,
        horizon_end=end,
        intervals=(
            HouseholdLoadForecastInterval(
                starts_at=start,
                ends_at=midpoint,
                expected_energy_wh=2400.0,
                confidence=confidence,
            ),
            HouseholdLoadForecastInterval(
                starts_at=midpoint,
                ends_at=end,
                expected_energy_wh=3600.0,
                confidence=0.9,
            ),
        ),
        historical_source_reference="history:comparable-recent-periods:v1",
        method_version="weighted-history-v1",
    )


def _strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="objective-map-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def _snapshot(load_forecast: HouseholdLoadForecast | None) -> PlanningInputSnapshot:
    captured_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    horizon_end = captured_at + timedelta(hours=36)
    return PlanningInputSnapshot(
        snapshot_id="snapshot-adr037",
        captured_at=captured_at,
        horizon_end=horizon_end,
        strategy=_strategy(),
        household_state=HouseholdState(measured_at=captured_at, phases=()),
        forecasts=ForecastSet(series=()),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("initial_planner_run",),
        household_load_forecast=load_forecast,
    )


def test_household_load_forecast_is_deterministic_and_explainable() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=36)
    forecast = _load_forecast(start, end, confidence=0.65)

    assert forecast.expected_energy_wh == 6000.0
    assert forecast.confidence == 0.65
    assert forecast.method_version == "weighted-history-v1"
    assert forecast.historical_source_reference.startswith("history:")


def test_household_load_forecast_rejects_gaps() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    with pytest.raises(ValueError, match="must be contiguous"):
        HouseholdLoadForecast(
            forecast_id="bad-gap",
            created_at=start,
            horizon_start=start,
            horizon_end=end,
            intervals=(
                HouseholdLoadForecastInterval(start, start + timedelta(minutes=30), 100.0, 0.5),
                HouseholdLoadForecastInterval(start + timedelta(hours=1), end, 200.0, 0.5),
            ),
            historical_source_reference="history:v1",
            method_version="method-v1",
        )


def test_planning_snapshot_remains_valid_without_history() -> None:
    snapshot = _snapshot(None)
    assert snapshot.household_load_forecast is None


def test_planning_snapshot_accepts_matching_household_load_horizon() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=36)
    forecast = _load_forecast(start, end)
    snapshot = _snapshot(forecast)

    assert snapshot.household_load_forecast is forecast


def test_planning_snapshot_rejects_mismatched_load_horizon() -> None:
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    forecast = _load_forecast(start, start + timedelta(hours=24))
    with pytest.raises(ValueError, match="complete planning horizon"):
        _snapshot(forecast)


def test_storage_requirement_is_evidence_not_implicit_grid_permission() -> None:
    deadline = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    requirement = StorageEnergyRequirement(
        requirement_id="storage:req:evening",
        required_by=deadline,
        required_energy_wh=6400.0,
        required_soc_percent=80.0,
        reason=StorageRequirementReason.HOUSEHOLD_DEMAND,
        confidence=0.85,
        evidence_ids=("household-load-v1", "pv-forecast-v4"),
        reserve_energy_wh=800.0,
    )

    assert requirement.required_energy_wh == 6400.0
    assert ChargeSourcePolicy.PV_ONLY != ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED


def test_storage_requirement_rejects_invalid_soc() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        StorageEnergyRequirement(
            requirement_id="storage:req:bad",
            required_by=datetime(2026, 8, 12, 18, 0, tzinfo=UTC),
            required_energy_wh=1000.0,
            required_soc_percent=101.0,
            reason=StorageRequirementReason.CONSERVATIVE_RESERVE,
            confidence=0.4,
            evidence_ids=("fallback",),
        )
