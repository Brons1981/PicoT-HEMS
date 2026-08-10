from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.planner.price_driven_strategy_v2 import (
    PriceDrivenStrategyV2,
    PriceDrivenStrategyV2Config,
)

BASE = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


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
        forecast_id="price-v2-test",
        kind=ForecastKind.ENERGY_PRICE,
        source="test",
        created_at=BASE - timedelta(minutes=5),
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=points,
    )


def test_keeps_multiple_price_opportunities_available() -> None:
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.03),
        _forecast((0.30, 0.11, 0.12, 0.28, 0.10, 0.13, 0.29, 0.12)),
        evaluated_at=BASE + timedelta(minutes=30),
    )

    assert len(decision.opportunities) == 3
    assert decision.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert decision.next_evaluation_at == BASE + timedelta(hours=1)
    assert decision.next_opportunity_rank is not None


def test_uses_bidirectional_mode_inside_any_qualifying_opportunity() -> None:
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.03),
        _forecast((0.30, 0.11, 0.12, 0.28, 0.10, 0.13, 0.29)),
        evaluated_at=BASE + timedelta(hours=4, minutes=15),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert decision.active_opportunity_rank is not None
    active = next(
        item for item in decision.opportunities if item.rank == decision.active_opportunity_rank
    )
    assert decision.next_evaluation_at == active.ends_at


def test_later_opportunity_remains_available_after_earlier_one_ends() -> None:
    strategy = PriceDrivenStrategyV2()
    config = PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.02)
    forecast = _forecast((0.30, 0.10, 0.11, 0.30, 0.12, 0.30))

    first = strategy.evaluate(
        config,
        forecast,
        evaluated_at=BASE + timedelta(hours=1, minutes=15),
    )
    later = strategy.evaluate(
        config,
        forecast,
        evaluated_at=BASE + timedelta(hours=3, minutes=15),
    )

    assert first.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    assert later.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert later.next_evaluation_at == BASE + timedelta(hours=4)
    assert len(later.opportunities) == len(first.opportunities)


def test_threshold_is_derived_from_daily_minimum_plus_margin() -> None:
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.04),
        _forecast((0.25, 0.15, 0.19, 0.22)),
        evaluated_at=BASE,
    )

    assert decision.daily_minimum_price_eur_per_kwh == pytest.approx(0.15)
    assert decision.price_threshold_eur_per_kwh == pytest.approx(0.19)


def test_disabled_strategy_returns_no_primitive_or_opportunities() -> None:
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(
            max_price_above_daily_min_eur_per_kwh=0.04,
            enabled=False,
        ),
        _forecast((0.20, 0.10, 0.20)),
        evaluated_at=BASE,
    )

    assert decision.primitive is None
    assert decision.opportunities == ()
    assert decision.next_evaluation_at is None


def test_no_remaining_opportunity_after_last_window() -> None:
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.01),
        _forecast((0.10, 0.11, 0.30, 0.35)),
        evaluated_at=BASE + timedelta(hours=3, minutes=15),
    )

    assert decision.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
    assert decision.next_evaluation_at is None
    assert decision.next_opportunity_rank is None
