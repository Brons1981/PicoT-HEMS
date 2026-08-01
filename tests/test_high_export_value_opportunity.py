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
from picot.domain.opportunity import OpportunityKind, OpportunityMetricKind
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.opportunity_engine import OpportunityEngine

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def _point(hour: int, value: float, confidence: float = 0.9) -> ForecastPoint:
    return ForecastPoint(
        starts_at=BASE + timedelta(hours=hour),
        ends_at=BASE + timedelta(hours=hour + 1),
        value=value,
        confidence=confidence,
    )


def _snapshot(points: tuple[ForecastPoint, ...], unit: str = "EUR/kWh") -> PlanningInputSnapshot:
    forecast = ForecastSeries(
        forecast_id="price-forecast-high-v1",
        kind=ForecastKind.ENERGY_PRICE,
        source="logical-price-source",
        created_at=BASE - timedelta(minutes=5),
        expires_at=BASE + timedelta(hours=6),
        unit=unit,
        points=points,
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-high-export-value-1",
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


def test_engine_detects_contiguous_high_export_value_window() -> None:
    snapshot = _snapshot(
        (
            _point(0, 0.18),
            _point(1, 0.31, 0.95),
            _point(2, 0.31, 0.80),
            _point(3, 0.14),
        )
    )

    result = OpportunityEngine().detect(snapshot)
    highest = tuple(
        item
        for item in result.opportunities
        if item.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
    )

    assert len(highest) == 1
    opportunity = highest[0]
    assert opportunity.starts_at == BASE + timedelta(hours=1)
    assert opportunity.ends_at == BASE + timedelta(hours=3)
    assert opportunity.confidence == 0.80
    assert opportunity.evidence[0].point_indexes == (1, 2)
    assert opportunity.metrics[0].kind is OpportunityMetricKind.ENERGY_PRICE_EUR_PER_KWH
    assert opportunity.metrics[0].value == 0.31


def test_engine_creates_separate_windows_for_equal_non_contiguous_maxima() -> None:
    snapshot = _snapshot(
        (
            _point(0, 0.30),
            _point(1, 0.12),
            _point(2, 0.30),
        )
    )

    result = OpportunityEngine().detect(snapshot)
    highest = tuple(
        item
        for item in result.opportunities
        if item.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
    )

    assert len(highest) == 2


def test_engine_skips_high_export_value_detection_for_unknown_unit() -> None:
    snapshot = _snapshot((_point(0, 10.0), _point(1, 15.0)), unit="ct/kWh")

    result = OpportunityEngine().detect(snapshot)

    assert all(
        item.kind is not OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
        for item in result.opportunities
    )
