"""Published reference prices are not executable historical opportunities."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_independent_daily_tariff_adapter import _snapshot

from picot.v2.independent_daily_tariff_adapter import (
    DailyReferenceTariffInputError,
    IndependentDailyTariffAdapter,
)


def test_reference_includes_elapsed_cheap_hours_but_default_schedule_starts_now():
    start = datetime(2026, 9, 9, tzinfo=UTC)
    source = _snapshot(start, hours=24)
    template = source.price_points[0]
    prices = tuple(replace(
        template, point_id=f"price-{i}", starts_at=start + timedelta(hours=i),
        ends_at=start + timedelta(hours=i + 1), value_eur_per_kwh=0.05 if i < 6 else 0.30,
    ) for i in range(24))
    source = replace(
        source, captured_at=start + timedelta(hours=12),
        price_points=prices[12:], published_price_points=prices,
    )
    adapter = IndependentDailyTariffAdapter()
    reference = adapter.build(source, horizon_start=start)
    future = adapter.build(source)
    assert len(reference.intervals) == 24
    assert min(i.import_eur_per_kwh for i in reference.intervals) == 0.05
    assert len(future.intervals) == 12
    assert all(i.starts_at >= source.captured_at for i in future.intervals)
    assert min(i.import_eur_per_kwh for i in future.intervals) == 0.30
    # Incomplete explicit publication must remain blocked, even if another
    # input contains prices that could hide the missing reference evidence.
    incomplete = replace(source, published_price_points=prices[1:], price_points=prices)
    with pytest.raises(DailyReferenceTariffInputError, match="coverage_incomplete"):
        adapter.build(incomplete, horizon_start=start)
