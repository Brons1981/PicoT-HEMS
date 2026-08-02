from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.planner.price_driven_strategy import (
    PriceDrivenStrategy,
    PriceDrivenStrategyConfig,
)

BASE = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)


def _forecast(values: tuple[float, ...]) -> ForecastSeries:
    points = tuple(
        ForecastPoint(
            starts_at=BASE + timedelta(hours=index),
            ends_at=BASE + timedelta(hours=index + 1),
            value=value,
            confidence=1.0,
        )
        for index, value in enumerate(values)
    )
    return ForecastSeries(
        forecast_id="price-forecast-1",
        kind=ForecastKind.ENERGY_PRICE,
        source="home-assistant",
        created_at=BASE - timedelta(minutes=5),
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=points,
    )


def test_waits_for_cheapest_contiguous_window() -> None:
    decision = PriceDrivenStrategy().evaluate(
        PriceDrivenStrategyConfig(window_points=2),
        _forecast((0.30, 0.20, 0.10, 0.11, 0.25)),
        evaluated_at=BASE + timedelta(minutes=30),
    )

    assert decision.window_starts_at == BASE + timedelta(hours=2)
    assert decision.window_ends_at == BASE + timedelta(hours=4)
    assert decision.average_price_eur_per_kwh == pytest.approx(0.105)
    assert decision.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert decision.next_evaluation_at == decision.window_starts_at


def test_uses_bidirectional_mode_inside_selected_window() -> None:
    decision = PriceDrivenStrategy().evaluate(
        PriceDrivenStrategyConfig(window_points=2),
        _forecast((0.30, 0.20, 0.10, 0.11, 0.25)),
        evaluated_at=BASE + timedelta(hours=2, minutes=15),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert decision.current_price_eur_per_kwh == 0.10
    assert decision.next_evaluation_at == BASE + timedelta(hours=4)


def test_equal_average_uses_earliest_window() -> None:
    decision = PriceDrivenStrategy().evaluate(
        PriceDrivenStrategyConfig(window_points=2),
        _forecast((0.10, 0.20, 0.20, 0.10)),
        evaluated_at=BASE,
    )

    assert decision.window_starts_at == BASE
    assert decision.window_ends_at == BASE + timedelta(hours=2)


def test_rejects_expired_forecast() -> None:
    forecast = _forecast((0.10, 0.20))

    with pytest.raises(ValueError, match="expired"):
        PriceDrivenStrategy().evaluate(
            PriceDrivenStrategyConfig(window_points=1),
            forecast,
            evaluated_at=forecast.expires_at,
        )
