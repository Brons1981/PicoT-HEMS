"""ADR-019.2 price evidence is not a charge commitment or net-profit proof."""

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.market_user_rule import MarketUserRule
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.market_price_windows import market_price_alternatives

BASE = datetime(2026, 9, 8, tzinfo=UTC)


def tariffs(hours=24):
    points = tuple(
        DailyReferenceTariffInterval(
            BASE + timedelta(minutes=15 * n),
            BASE + timedelta(minutes=15 * (n + 1)),
            0.1 if 8 <= n < 20 else 0.3,
            0.8 if n == 72 else 0.5 if 73 <= n < 80 else 0.1,
            1.0,
            (f"price-{n}",),
        )
        for n in range(hours * 4)
    )
    return DailyReferenceTariffSchedule(
        "prices", "snapshot", BASE, BASE + timedelta(hours=hours), points, "test"
    )


def alternatives(**updates):
    args = dict(
        rule=MarketUserRule("trade", 1, 0.25, 0.2),
        tariffs=tariffs(),
        delivery_start=BASE,
        delivery_end=BASE + timedelta(days=1),
        earliest_export=BASE,
        usable_capacity_wh=8160,
        charge_power_w=2400,
        discharge_power_w=2400,
        conversion=StorageConversionModel("explicit", 0.8, 0.9, ("conversion",), "test"),
    )
    args.update(updates)
    return market_price_alternatives(**args)


def test_same_battery_energy_different_grid_energy_and_duration():
    result = max(alternatives(), key=lambda e: e.spread_eur_per_kwh)
    assert result.battery_energy_wh == 2040
    assert result.export_window.grid_energy_wh == pytest.approx(1836)
    assert result.reference_window.grid_energy_wh == pytest.approx(2550)
    assert result.export_window.ends_at - result.export_window.starts_at == timedelta(minutes=45.9)
    assert result.reference_window.ends_at - result.reference_window.starts_at == timedelta(
        minutes=63.75
    )
    assert result.export_window.starts_at == BASE + timedelta(hours=18)
    # 600Wh at .8 and 1236Wh at .5, not the isolated highest quarter-hour price.
    assert result.export_window.average_eur_per_kwh == pytest.approx(
        (600 * 0.8 + 1236 * 0.5) / 1836
    )
    assert result.reference_window.average_eur_per_kwh == pytest.approx(0.1)
    assert result.reference_window.fictitious
    assert not result.export_window.fictitious
    assert result.meets_spread
    assert result.export_window.parts[-1].grid_energy_wh == pytest.approx(36)


def test_past_cheap_reference_is_allowed_but_past_export_is_not():
    earliest = BASE + timedelta(hours=19)
    result = alternatives(earliest_export=earliest)
    assert result
    assert all(e.export_window.starts_at >= earliest for e in result)
    assert all(e.reference_window.ends_at < earliest for e in result)


@pytest.mark.parametrize("hours", [23, 24, 25])
def test_actual_delivery_duration_is_used(hours):
    result = alternatives(tariffs=tariffs(hours), delivery_end=BASE + timedelta(hours=hours))
    assert result
    assert all(e.export_window.ends_at <= BASE + timedelta(hours=hours) for e in result)


def test_no_shortened_action_if_full_amount_does_not_fit():
    assert alternatives(earliest_export=BASE + timedelta(hours=23, minutes=50)) == ()


def test_missing_day_prices_are_not_invented():
    with pytest.raises(ValueError, match="complete published"):
        alternatives(tariffs=tariffs(23))


def test_spread_threshold_is_explicit_and_does_not_schedule_recovery():
    result = alternatives(rule=MarketUserRule("trade", 2, 0.25, 1.0, True))
    assert result and not any(e.meets_spread for e in result)
    assert all(e.reference_window.fictitious for e in result)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_invalid_power_is_rejected(value):
    with pytest.raises(ValueError):
        alternatives(charge_power_w=value)
