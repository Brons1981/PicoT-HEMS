from datetime import UTC, datetime, timedelta

import pytest

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.opportunity_engine import (
    HIGH_EXPORT_VALUE_WINDOW,
    LOWEST_PRICE_WINDOW,
    NEGATIVE_PRICE_WINDOW,
    OpportunityEngine,
    PriceOpportunityConfig,
)


def point(point_id: str, start: datetime, value: float, *, confidence: float = 1.0) -> PriceForecastPoint:
    return PriceForecastPoint(
        point_id=point_id,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        value_eur_per_kwh=value,
        confidence=confidence,
        evidence_id="forecast-adr036-validation",
    )


def snapshot(*, captured_at: datetime, horizon_end: datetime, points: tuple[PriceForecastPoint, ...]) -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        run_id="run-adr036-validation",
        snapshot_id="snapshot-adr036-validation",
        captured_at=captured_at,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=horizon_end,
        price_points=points,
    )


def config(*, low_margin: float = 0.02, high_margin: float = 0.02) -> PriceOpportunityConfig:
    return PriceOpportunityConfig(
        low_price_margin_eur_per_kwh=low_margin,
        high_price_margin_eur_per_kwh=high_margin,
        config_version=f"adr036-validation:low={low_margin:.6f}:high={high_margin:.6f}",
    )


def test_negative_price_detection_is_absolute_and_strict() -> None:
    base = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    source = snapshot(
        captured_at=base,
        horizon_end=base + timedelta(hours=4),
        points=(
            point("p0", base, -0.01),
            point("p1", base + timedelta(hours=1), 0.00),
            point("p2", base + timedelta(hours=2), -0.02),
            point("p3", base + timedelta(hours=3), 0.05),
        ),
    )

    result = OpportunityEngine().detect(source, price_config=config())
    negative = tuple(item for item in result.opportunities if item.kind == NEGATIVE_PRICE_WINDOW)

    assert len(negative) == 2
    assert negative[0].starts_at == base
    assert negative[0].ends_at == base + timedelta(hours=1)
    assert negative[1].starts_at == base + timedelta(hours=2)
    assert negative[1].ends_at == base + timedelta(hours=3)
    assert all(item.metrics.boundary_eur_per_kwh == 0.0 for item in negative)
    assert all(item.metrics.bridged_interval_count == 0 for item in negative)


def test_high_export_window_can_bridge_one_internal_excursion() -> None:
    base = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    source = snapshot(
        captured_at=base,
        horizon_end=base + timedelta(hours=4),
        points=(
            point("p0", base, 0.50, confidence=0.95),
            point("p1", base + timedelta(hours=1), 0.44, confidence=0.80),
            point("p2", base + timedelta(hours=2), 0.50, confidence=0.90),
            point("p3", base + timedelta(hours=3), 0.10),
        ),
    )

    result = OpportunityEngine().detect(
        source,
        price_config=config(low_margin=0.0, high_margin=0.05),
    )
    high = tuple(item for item in result.opportunities if item.kind == HIGH_EXPORT_VALUE_WINDOW)

    assert len(high) == 1
    window = high[0]
    assert window.starts_at == base
    assert window.ends_at == base + timedelta(hours=3)
    assert window.metrics.boundary_eur_per_kwh == pytest.approx(0.45)
    assert window.metrics.average_price_eur_per_kwh == pytest.approx(0.48)
    assert window.metrics.source_interval_count == 3
    assert window.metrics.bridged_interval_count == 1
    assert window.confidence == pytest.approx(0.80)
    assert window.evidence[0].point_ids == ("p0", "p1", "p2")


def test_relative_price_reference_is_independent_per_market_date() -> None:
    base = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)
    source = snapshot(
        captured_at=base,
        horizon_end=base + timedelta(hours=4),
        points=(
            point("d1-low", base, 0.10),
            point("d1-high", base + timedelta(hours=1), 0.30),
            point("d2-low", base + timedelta(hours=2), 0.01),
            point("d2-high", base + timedelta(hours=3), 0.50),
        ),
    )

    result = OpportunityEngine().detect(
        source,
        price_config=config(low_margin=0.0, high_margin=0.0),
    )
    low = tuple(item for item in result.opportunities if item.kind == LOWEST_PRICE_WINDOW)

    assert len(low) == 2
    assert low[0].starts_at == base
    assert low[0].metrics.minimum_price_eur_per_kwh == pytest.approx(0.10)
    assert low[1].starts_at == base + timedelta(hours=2)
    assert low[1].metrics.minimum_price_eur_per_kwh == pytest.approx(0.01)


def test_relative_window_never_bridges_across_local_market_midnight() -> None:
    base = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)
    source = snapshot(
        captured_at=base,
        horizon_end=base + timedelta(hours=4),
        points=(
            point("before-midnight-low", base, 0.10),
            point("before-midnight-excursion", base + timedelta(hours=1), 0.20),
            point("after-midnight-low", base + timedelta(hours=2), 0.10),
            point("after-midnight-high", base + timedelta(hours=3), 0.30),
        ),
    )

    result = OpportunityEngine().detect(
        source,
        price_config=config(low_margin=0.0, high_margin=0.0),
    )
    low = tuple(item for item in result.opportunities if item.kind == LOWEST_PRICE_WINDOW)

    assert len(low) == 2
    midnight_utc = base + timedelta(hours=2)
    assert low[0].ends_at <= midnight_utc
    assert low[1].starts_at >= midnight_utc
    assert all(
        not (item.starts_at < midnight_utc and item.ends_at > midnight_utc)
        for item in low
    )


def test_only_price_points_overlapping_the_rolling_horizon_are_used() -> None:
    captured = datetime(2026, 8, 13, 10, 30, tzinfo=UTC)
    horizon_end = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    source = snapshot(
        captured_at=captured,
        horizon_end=horizon_end,
        points=(
            point("past", datetime(2026, 8, 13, 9, 0, tzinfo=UTC), -0.20),
            point("overlap-start", datetime(2026, 8, 13, 10, 0, tzinfo=UTC), -0.10),
            point("inside", datetime(2026, 8, 13, 11, 0, tzinfo=UTC), -0.05),
            point("after", datetime(2026, 8, 13, 12, 0, tzinfo=UTC), -0.30),
        ),
    )

    result = OpportunityEngine().detect(source, price_config=config())
    negative = tuple(item for item in result.opportunities if item.kind == NEGATIVE_PRICE_WINDOW)

    assert len(negative) == 1
    window = negative[0]
    assert window.starts_at == datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    assert window.ends_at == datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    assert window.evidence[0].point_ids == ("overlap-start", "inside")
