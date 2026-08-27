from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.independent_daily_tariff_adapter import (
    ENERGY_TAX_EX_VAT_EUR_PER_KWH,
    EXPORT_ADDITION_EUR_PER_KWH,
    SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH,
    VAT_FACTOR,
    DailyReferenceTariffInputError,
    IndependentDailyTariffAdapter,
)


def _snapshot(starts_at: datetime, *, hours: int = 2) -> PlanningInputSnapshot:
    ends_at = starts_at + timedelta(hours=hours)
    return PlanningInputSnapshot(
        run_id="run",
        snapshot_id="snapshot",
        captured_at=starts_at,
        picot_version="2.0.0-dev.140",
        architecture_baseline_commit="baseline",
        pipeline_contract_version=1,
        strategy_id="strategy",
        horizon_end=ends_at,
        price_points=(
            PriceForecastPoint(
                point_id="price",
                starts_at=starts_at,
                ends_at=ends_at,
                value_eur_per_kwh=0.30,
                confidence=0.9,
                evidence_id="nordpool",
            ),
        ),
    )


def test_2026_tariff_separates_quarter_offset_and_cross_quarter_saldering() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(datetime(2026, 12, 31, 20, 0, tzinfo=timezone(timedelta(hours=1))))
    )

    assert result.intervals[0].import_eur_per_kwh == pytest.approx(0.30)
    interval = result.intervals[0]
    energy_tax = ENERGY_TAX_EX_VAT_EUR_PER_KWH * VAT_FACTOR
    bare_market_price = 0.30 - (
        ENERGY_TAX_EX_VAT_EUR_PER_KWH
        + SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH
    ) * VAT_FACTOR
    cross_quarter_export = bare_market_price + EXPORT_ADDITION_EUR_PER_KWH

    assert interval.import_eur_per_kwh == pytest.approx(0.30)
    assert interval.same_interval_offset_eur_per_kwh == pytest.approx(0.30)
    assert interval.cross_interval_export_eur_per_kwh == pytest.approx(
        cross_quarter_export
    )
    assert interval.saldering_tax_eur_per_kwh == pytest.approx(energy_tax)
    assert interval.export_eur_per_kwh == pytest.approx(
        cross_quarter_export + energy_tax
    )
    assert "nl-quarter-netting-and-energy-tax-saldering-through-2026" in (
        interval.evidence_ids
    )


def test_2027_export_is_bare_market_price_plus_exact_contract_addition() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(datetime(2027, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=1))))
    )

    bare_market_price = 0.30 - (
        ENERGY_TAX_EX_VAT_EUR_PER_KWH
        + SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH
    ) * VAT_FACTOR
    expected = bare_market_price + EXPORT_ADDITION_EUR_PER_KWH
    assert result.intervals[0].import_eur_per_kwh == pytest.approx(0.30)
    assert result.intervals[0].export_eur_per_kwh == pytest.approx(expected)
    assert result.intervals[0].same_interval_offset_eur_per_kwh is None
    assert result.intervals[0].cross_interval_export_eur_per_kwh == pytest.approx(
        expected
    )
    assert result.intervals[0].saldering_tax_eur_per_kwh == 0.0
    assert "nl-export-bare-market-plus-0.02-2027" in result.intervals[0].evidence_ids


def test_transition_is_split_exactly_at_2027_boundary() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(
            datetime(2026, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=1)))
        )
    )

    assert len(result.intervals) == 2
    assert result.intervals[0].saldering_tax_eur_per_kwh > 0.0
    assert result.intervals[1].export_eur_per_kwh < 0.30
    assert result.intervals[1].saldering_tax_eur_per_kwh == 0.0


def test_missing_price_coverage_blocks_schedule() -> None:
    snapshot = _snapshot(datetime(2026, 8, 23, 10, 0, tzinfo=UTC))
    short = replace(
        snapshot.price_points[0],
        ends_at=snapshot.horizon_end - timedelta(minutes=15),
    )
    with pytest.raises(DailyReferenceTariffInputError, match="coverage_incomplete"):
        IndependentDailyTariffAdapter().build(
            replace(snapshot, price_points=(short,))
        )


def test_explicit_daily_horizon_does_not_require_canonical_36_hour_coverage() -> None:
    starts_at = datetime(2026, 8, 23, 18, 30, tzinfo=UTC)
    canonical_end = starts_at + timedelta(hours=36)
    daily_end = starts_at + timedelta(hours=24)
    snapshot = replace(
        _snapshot(starts_at, hours=36),
        price_points=(
            PriceForecastPoint(
                point_id="known-day-prices",
                starts_at=starts_at,
                ends_at=daily_end,
                value_eur_per_kwh=0.30,
                confidence=1.0,
                evidence_id="nordpool-today-and-tomorrow",
            ),
        ),
    )
    assert snapshot.horizon_end == canonical_end

    result = IndependentDailyTariffAdapter().build(
        snapshot,
        horizon_end=daily_end,
    )

    assert result.horizon_start == starts_at
    assert result.horizon_end == daily_end


def test_published_horizon_ends_at_last_contiguous_known_price() -> None:
    starts_at = datetime(2026, 8, 24, 0, 32, tzinfo=timezone(timedelta(hours=2)))
    market_day_end = datetime(2026, 8, 25, 0, 0, tzinfo=starts_at.tzinfo)
    snapshot = replace(
        _snapshot(starts_at, hours=36),
        price_points=(PriceForecastPoint(
            point_id="published-current-market-day",
            starts_at=starts_at.replace(minute=30),
            ends_at=market_day_end,
            value_eur_per_kwh=0.30,
            confidence=1.0,
            evidence_id="nordpool-today",
        ),),
    )

    result = IndependentDailyTariffAdapter().published_horizon_end(
        snapshot,
        maximum_horizon_end=starts_at + timedelta(hours=24),
    )

    assert result == market_day_end


def test_published_horizon_is_capped_at_24_hours_after_next_prices_arrive() -> None:
    starts_at = datetime(2026, 8, 24, 15, 0, tzinfo=timezone(timedelta(hours=2)))
    snapshot = _snapshot(starts_at, hours=36)

    result = IndependentDailyTariffAdapter().published_horizon_end(
        snapshot,
        maximum_horizon_end=starts_at + timedelta(hours=24),
    )

    assert result == starts_at + timedelta(hours=24)
