from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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

BASE = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)


def _point(hour: float, value: float, duration_minutes: int = 60) -> ForecastPoint:
    starts_at = BASE + timedelta(hours=hour)
    return ForecastPoint(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=duration_minutes),
        value=value,
        confidence=0.9,
    )


def _snapshot(
    points: tuple[ForecastPoint, ...],
    *,
    captured_at: datetime,
    horizon_hours: int,
) -> PlanningInputSnapshot:
    forecast = ForecastSeries(
        forecast_id="price-forecast-adr036",
        kind=ForecastKind.ENERGY_PRICE,
        source="logical-price-source",
        created_at=captured_at - timedelta(minutes=5),
        expires_at=captured_at + timedelta(hours=horizon_hours + 1),
        unit="EUR/kWh",
        points=points,
    )
    return PlanningInputSnapshot(
        snapshot_id="snapshot-adr036",
        captured_at=captured_at,
        horizon_end=captured_at + timedelta(hours=horizon_hours),
        strategy=PlannerStrategy(
            strategy_version=1,
            source_profile_version=1,
            mapping_version="objective-map-v1",
            optimisation_profile=OptimisationProfile.BALANCED,
            objectives=(),
        ),
        household_state=HouseholdState(measured_at=captured_at, phases=()),
        forecasts=ForecastSet(series=(forecast,)),
        runtime_state=RuntimePressureState.NORMAL,
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("next_day_prices_available",),
    )


def _opportunities(
    snapshot: PlanningInputSnapshot,
    config: PriceOpportunityDetectionConfig,
    kind: OpportunityKind,
) -> tuple[Opportunity, ...]:
    return tuple(
        item
        for item in OpportunityEngine().detect(snapshot, price_config=config).opportunities
        if item.kind is kind
    )


def _metrics(opportunity: Opportunity) -> dict[OpportunityMetricKind, float]:
    return {metric.kind: metric.value for metric in opportunity.metrics}


def test_relative_price_reference_is_per_market_day_inside_one_rolling_horizon() -> None:
    captured_at = BASE + timedelta(hours=15)
    points = (
        _point(10, 0.10),
        _point(16, 0.12),
        _point(17, 0.13),
        _point(24 + 1, 0.08),
        _point(24 + 11, 0.01),
        _point(24 + 12, 0.03),
        _point(24 + 20, 0.18),
    )
    snapshot = _snapshot(points, captured_at=captured_at, horizon_hours=36)
    config = PriceOpportunityDetectionConfig(
        config_version=1,
        low_price_margin_eur_per_kwh=0.03,
        high_price_margin_eur_per_kwh=0.03,
    )

    low = _opportunities(snapshot, config, OpportunityKind.LOWEST_PRICE_WINDOW)

    assert any(item.starts_at == BASE + timedelta(hours=16) for item in low)
    assert any(item.starts_at == BASE + timedelta(hours=24 + 11) for item in low)
    today = next(item for item in low if item.starts_at == BASE + timedelta(hours=16))
    tomorrow = next(
        item for item in low if item.starts_at == BASE + timedelta(hours=24 + 11)
    )
    assert _metrics(today)[OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH] == 0.10
    assert _metrics(tomorrow)[OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH] == 0.01


def test_one_non_qualifying_interval_can_be_bridged_when_merged_average_qualifies() -> None:
    captured_at = BASE
    points = (
        _point(0, 0.10),
        _point(1, 0.12),
        _point(2, 0.16),
        _point(3, 0.11),
    )
    snapshot = _snapshot(points, captured_at=captured_at, horizon_hours=4)
    config = PriceOpportunityDetectionConfig(
        config_version=7,
        low_price_margin_eur_per_kwh=0.03,
        high_price_margin_eur_per_kwh=0.03,
    )

    low = _opportunities(snapshot, config, OpportunityKind.LOWEST_PRICE_WINDOW)

    assert len(low) == 1
    assert low[0].starts_at == BASE
    assert low[0].ends_at == BASE + timedelta(hours=4)
    assert low[0].evidence[0].point_indexes == (0, 1, 2, 3)
    metrics = _metrics(low[0])
    assert metrics[OpportunityMetricKind.BRIDGED_INTERVAL_COUNT] == 1.0
    assert metrics[OpportunityMetricKind.SOURCE_INTERVAL_COUNT] == 4.0
    assert metrics[OpportunityMetricKind.PRICE_DETECTION_CONFIG_VERSION] == 7.0


def test_bridge_is_rejected_when_merged_average_breaks_low_price_boundary() -> None:
    captured_at = BASE
    points = (
        _point(0, 0.10),
        _point(1, 0.12),
        _point(2, 0.30),
        _point(3, 0.11),
    )
    snapshot = _snapshot(points, captured_at=captured_at, horizon_hours=4)
    config = PriceOpportunityDetectionConfig(
        config_version=1,
        low_price_margin_eur_per_kwh=0.03,
        high_price_margin_eur_per_kwh=0.03,
    )

    low = _opportunities(snapshot, config, OpportunityKind.LOWEST_PRICE_WINDOW)

    assert len(low) == 2
    assert low[0].evidence[0].point_indexes == (0, 1)
    assert low[1].evidence[0].point_indexes == (3,)


def test_high_price_window_uses_symmetric_boundary_and_bridge_rule() -> None:
    captured_at = BASE
    points = (
        _point(0, 0.50),
        _point(1, 0.48),
        _point(2, 0.43),
        _point(3, 0.49),
    )
    snapshot = _snapshot(points, captured_at=captured_at, horizon_hours=4)
    config = PriceOpportunityDetectionConfig(
        config_version=1,
        low_price_margin_eur_per_kwh=0.03,
        high_price_margin_eur_per_kwh=0.03,
    )

    high = _opportunities(snapshot, config, OpportunityKind.HIGH_EXPORT_VALUE_WINDOW)

    assert len(high) == 1
    assert high[0].evidence[0].point_indexes == (0, 1, 2, 3)
    metrics = _metrics(high[0])
    assert metrics[OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH] == 0.50
    assert metrics[OpportunityMetricKind.PRICE_BOUNDARY_EUR_PER_KWH] == 0.47
    assert metrics[OpportunityMetricKind.BRIDGED_INTERVAL_COUNT] == 1.0


def test_price_detection_config_rejects_hidden_or_invalid_margins() -> None:
    with pytest.raises(ValueError):
        PriceOpportunityDetectionConfig(
            config_version=1,
            low_price_margin_eur_per_kwh=-0.01,
            high_price_margin_eur_per_kwh=0.03,
        )

    with pytest.raises(ValueError):
        PriceOpportunityDetectionConfig(
            config_version=0,
            low_price_margin_eur_per_kwh=0.03,
            high_price_margin_eur_per_kwh=0.03,
        )
