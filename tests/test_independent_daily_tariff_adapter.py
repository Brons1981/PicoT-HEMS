from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.independent_daily_tariff_adapter import (
    ENERGY_TAX_EX_VAT_EUR_PER_KWH,
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


def test_2026_import_and_export_use_same_all_in_sensor_price() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(datetime(2026, 12, 31, 20, 0, tzinfo=timezone(timedelta(hours=1))))
    )

    assert result.intervals[0].import_eur_per_kwh == pytest.approx(0.30)
    assert result.intervals[0].export_eur_per_kwh == pytest.approx(0.30)
    assert "nl-net-metering-through-2026" in result.intervals[0].evidence_ids


def test_2027_export_removes_energy_tax_including_vat() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(datetime(2027, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=1))))
    )

    expected = 0.30 - ENERGY_TAX_EX_VAT_EUR_PER_KWH * VAT_FACTOR
    assert result.intervals[0].import_eur_per_kwh == pytest.approx(0.30)
    assert result.intervals[0].export_eur_per_kwh == pytest.approx(expected)
    assert "nl-export-energy-tax-removed-2027" in result.intervals[0].evidence_ids


def test_transition_is_split_exactly_at_2027_boundary() -> None:
    result = IndependentDailyTariffAdapter().build(
        _snapshot(
            datetime(2026, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=1)))
        )
    )

    assert len(result.intervals) == 2
    assert result.intervals[0].export_eur_per_kwh == pytest.approx(0.30)
    assert result.intervals[1].export_eur_per_kwh < 0.30


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
