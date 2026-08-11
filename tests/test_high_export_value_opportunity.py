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
from picot.domain.opportunity import Opportunity, OpportunityKind, OpportunityMetricKind
from picot.domain.planning_input_snapshot import (
    PlanningInputSnapshot,
    PlanningInputVersions,
    RuntimePressureState,
)
from picot.planner.opportunity_engine import OpportunityEngine
from picot.planner.price_opportunity_detection import PriceOpportunityDetectionConfig

BASE = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
CONFIG = PriceOpportunityDetectionConfig(
    config_version=1,
    low_price_margin_eur_per_kwh=0.0,
    high_price_margin_eur_per_kwh=0.0,
)


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


def _highest(snapshot: PlanningInputSnapshot) -> tuple[Opportunity, ...]:
    return tuple(
        item
        for item in OpportunityEngine().detect(snapshot, price_config=CONFIG).opportunities
        if item.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
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

    highest = _highest(snapshot)

    assert len(highest) == 1
    opportunity = highest[0]
    assert opportunity.starts_at == BASE + timedelta(hours=1)
    assert opportunity.ends_at == BASE + timedelta(hours=3)
    assert opportunity.confidence == 0.80
    assert opportunity.evidence[0].point_indexes == (1, 2)
    metrics = {metric.kind: metric.value for metric in opportunity.metrics}
    assert metrics[OpportunityMetricKind.AVERAGE_ENERGY_PRICE_EUR_PER_KWH] == 0.31
    assert metrics[OpportunityMetricKind.MINIMUM_ENERGY_PRICE_EUR_PER_KWH] == 0.31
    assert metrics[OpportunityMetricKind.MAXIMUM_ENERGY_PRICE_EUR_PER_KWH] == 0.31
    assert metrics[OpportunityMetricKind.PRICE_BOUNDARY_EUR_PER_KWH] == 0.31
    assert metrics[OpportunityMetricKind.SOURCE_INTERVAL_COUNT] == 2.0
    assert metrics[OpportunityMetricKind.BRIDGED_INTERVAL_COUNT] == 0.0


def test_engine_creates_separate_windows_for_equal_non_contiguous_maxima() -> None:
    snapshot = _snapshot(
        (
            _point(0, 0.30),
            _point(1, 0.12),
            _point(2, 0.30),
        )
    )

    assert len(_highest(snapshot)) == 2


def test_engine_skips_high_export_value_detection_for_unknown_unit() -> None:
    snapshot = _snapshot((_point(0, 10.0), _point(1, 15.0)), unit="ct/kWh")

    result = OpportunityEngine().detect(snapshot, price_config=CONFIG)

    assert all(
        item.kind is not OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
        for item in result.opportunities
    )
