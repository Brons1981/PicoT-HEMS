from __future__ import annotations

from datetime import UTC, datetime, timedelta

from picot.domain.forecast import (
    ForecastKind,
    ForecastPoint,
    ForecastSeries,
    ForecastSet,
)
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.opportunity import OpportunityKind, OpportunityLifecycle
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.opportunity_engine import OpportunityEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _snapshot(points: tuple[ForecastPoint, ...]) -> PlanningInputSnapshot:
    forecast = ForecastSeries(
        forecast_id="price-forecast-v1",
        kind=ForecastKind.ENERGY_PRICE,
        source="logical-price-source",
        created_at=BASE - timedelta(minutes=5),
        expires_at=BASE + timedelta(hours=6),
        unit="EUR/kWh",
        points=points,
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-opportunity-1",
        captured_at=BASE,
        horizon_end=BASE + timedelta(hours=4),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=BASE, phases=()),
        forecasts=ForecastSet(series=(forecast,)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("price_forecast_changed",),
    )


def _point(hour: int, value: float, confidence: float = 0.9) -> ForecastPoint:
    return ForecastPoint(
        starts_at=BASE + timedelta(hours=hour),
        ends_at=BASE + timedelta(hours=hour + 1),
        value=value,
        confidence=confidence,
    )


def _negative_opportunities(snapshot: PlanningInputSnapshot):
    return tuple(
        opportunity
        for opportunity in OpportunityEngine().detect(snapshot).opportunities
        if opportunity.kind is OpportunityKind.NEGATIVE_PRICE_WINDOW
    )


def test_engine_detects_and_merges_contiguous_negative_price_points() -> None:
    snapshot = _snapshot(
        (
            _point(0, 0.12),
            _point(1, -0.03, 0.95),
            _point(2, -0.01, 0.80),
            _point(3, 0.08),
        )
    )

    opportunities = _negative_opportunities(snapshot)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.lifecycle is OpportunityLifecycle.DETECTED
    assert opportunity.starts_at == BASE + timedelta(hours=1)
    assert opportunity.ends_at == BASE + timedelta(hours=3)
    assert opportunity.confidence == 0.80
    assert opportunity.evidence[0].source_id == "price-forecast-v1"
    assert opportunity.evidence[0].point_indexes == (1, 2)


def test_engine_returns_no_negative_opportunity_when_no_negative_price_exists() -> None:
    snapshot = _snapshot((_point(0, 0.10), _point(1, 0.08)))

    assert _negative_opportunities(snapshot) == ()


def test_engine_creates_separate_windows_for_non_contiguous_negative_prices() -> None:
    snapshot = _snapshot(
        (
            _point(0, -0.02),
            _point(1, 0.04),
            _point(2, -0.01),
        )
    )

    opportunities = _negative_opportunities(snapshot)

    assert len(opportunities) == 2
    assert opportunities[0].opportunity_id.endswith(":1")
    assert opportunities[1].opportunity_id.endswith(":2")
