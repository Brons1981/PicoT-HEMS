from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.addon.price_runtime_v2 import _price_entry_observation
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.planner.price_driven_strategy_v2 import (
    PriceDrivenStrategyV2,
    PriceDrivenStrategyV2Config,
)

BASE = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _forecast(values: tuple[float, ...]) -> ForecastSeries:
    points = tuple(
        ForecastPoint(
            starts_at=BASE + timedelta(minutes=15 * index),
            ends_at=BASE + timedelta(minutes=15 * (index + 1)),
            value=value,
            confidence=1.0,
        )
        for index, value in enumerate(values)
    )
    return ForecastSeries(
        forecast_id="price-entry-observation-test",
        kind=ForecastKind.ENERGY_PRICE,
        source="test",
        created_at=BASE - timedelta(minutes=5),
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=points,
    )


def test_observation_flags_cheaper_later_entry_inside_same_opportunity() -> None:
    forecast = _forecast((0.20, 0.158, 0.164, 0.143, 0.134, 0.131, 0.127, 0.18))
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.04),
        forecast,
        evaluated_at=BASE,
    )

    observation = _price_entry_observation(decision, forecast)

    assert observation["price_entry_observation_only"] is True
    assert observation["price_entry_replan_input"] is False
    assert observation["price_entry_observation_status"] == "better_later_price_exists"
    assert observation["price_entry_reference_price_eur_per_kwh"] == pytest.approx(0.158)
    assert observation["price_entry_best_later_price_eur_per_kwh"] == pytest.approx(0.127)
    assert observation["price_entry_best_later_saving_eur_per_kwh"] == pytest.approx(0.031)
    assert observation["price_entry_best_later_starts_at"] == (
        BASE + timedelta(minutes=90)
    ).isoformat()

    alternatives = observation["price_entry_alternatives"]
    assert isinstance(alternatives, list)
    plus_30 = next(item for item in alternatives if item["delay_minutes"] == 30)
    assert plus_30["price_eur_per_kwh"] == pytest.approx(0.143)
    assert plus_30["cheaper_than_entry"] is True


def test_observation_reports_when_entry_is_already_lowest() -> None:
    forecast = _forecast((0.20, 0.127, 0.13, 0.14, 0.15, 0.20))
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(max_price_above_daily_min_eur_per_kwh=0.03),
        forecast,
        evaluated_at=BASE,
    )

    observation = _price_entry_observation(decision, forecast)

    assert observation["price_entry_observation_status"] == "entry_is_lowest_so_far"
    assert observation["price_entry_better_later_price_exists"] is False
    assert observation["price_entry_best_later_saving_eur_per_kwh"] <= 0.0
