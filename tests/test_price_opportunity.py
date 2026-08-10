from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.planner.price_opportunity import (
    PriceOpportunityAnalyzer,
    PriceOpportunityConfig,
)

BASE = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def _forecast(values: tuple[float, ...], *, step_minutes: int = 15) -> ForecastSeries:
    points = tuple(
        ForecastPoint(
            starts_at=BASE + timedelta(minutes=step_minutes * index),
            ends_at=BASE + timedelta(minutes=step_minutes * (index + 1)),
            value=value,
            confidence=1.0,
        )
        for index, value in enumerate(values)
    )
    return ForecastSeries(
        forecast_id="price-opportunity-test",
        kind=ForecastKind.ENERGY_PRICE,
        source="test",
        created_at=BASE - timedelta(minutes=5),
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=points,
    )


def test_finds_multiple_separate_opportunities() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.03),
        _forecast((0.30, 0.12, 0.13, 0.28, 0.11, 0.14, 0.29, 0.125)),
        evaluated_at=BASE + timedelta(minutes=5),
    )

    assert result.daily_minimum_price_eur_per_kwh == pytest.approx(0.11)
    assert result.price_threshold_eur_per_kwh == pytest.approx(0.14)
    assert len(result.opportunities) == 3
    assert {op.point_count for op in result.opportunities} == {1, 2}


def test_merges_adjacent_qualifying_points_into_one_opportunity() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.02),
        _forecast((0.25, 0.10, 0.11, 0.12, 0.30)),
        evaluated_at=BASE,
    )

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.starts_at == BASE + timedelta(minutes=15)
    assert opportunity.ends_at == BASE + timedelta(minutes=60)
    assert opportunity.point_count == 3
    assert opportunity.average_price_eur_per_kwh == pytest.approx(0.11)


def test_threshold_is_inclusive() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.04),
        _forecast((0.10, 0.14, 0.20)),
        evaluated_at=BASE,
    )

    assert len(result.opportunities) == 1
    assert result.opportunities[0].point_count == 2


def test_ranks_cheapest_average_first_and_keeps_all_candidates() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.05),
        _forecast((0.11, 0.12, 0.30, 0.10, 0.14, 0.30, 0.13)),
        evaluated_at=BASE,
    )

    assert [op.rank for op in result.opportunities] == [1, 2, 3]
    assert [op.average_price_eur_per_kwh for op in result.opportunities] == pytest.approx(
        [0.115, 0.12, 0.13]
    )


def test_zero_margin_selects_only_daily_minimum_points() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.0),
        _forecast((0.20, 0.10, 0.30, 0.10)),
        evaluated_at=BASE,
    )

    assert len(result.opportunities) == 2
    assert all(op.minimum_price_eur_per_kwh == pytest.approx(0.10) for op in result.opportunities)


def test_disabled_analyzer_returns_traceable_empty_set() -> None:
    result = PriceOpportunityAnalyzer().analyze(
        PriceOpportunityConfig(
            max_price_above_daily_min_eur_per_kwh=0.03,
            enabled=False,
        ),
        _forecast((0.20, 0.10, 0.11)),
        evaluated_at=BASE,
    )

    assert result.opportunities == ()
    assert result.daily_minimum_price_eur_per_kwh == pytest.approx(0.10)
    assert result.price_threshold_eur_per_kwh == pytest.approx(0.13)


def test_rejects_invalid_margin() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=-0.01)


def test_rejects_wrong_forecast_kind() -> None:
    forecast = _forecast((0.10, 0.20))
    wrong = ForecastSeries(
        forecast_id=forecast.forecast_id,
        kind=ForecastKind.PV_POWER,
        source=forecast.source,
        created_at=forecast.created_at,
        expires_at=forecast.expires_at,
        unit=forecast.unit,
        points=forecast.points,
    )

    with pytest.raises(ValueError, match="energy-price"):
        PriceOpportunityAnalyzer().analyze(
            PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.03),
            wrong,
            evaluated_at=BASE,
        )


def test_rejects_expired_forecast() -> None:
    forecast = _forecast((0.10, 0.20))

    with pytest.raises(ValueError, match="expired"):
        PriceOpportunityAnalyzer().analyze(
            PriceOpportunityConfig(max_price_above_daily_min_eur_per_kwh=0.03),
            forecast,
            evaluated_at=forecast.expires_at,
        )
