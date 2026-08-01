from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries, ForecastSet


def _point(start: datetime, *, confidence: float = 0.8) -> ForecastPoint:
    return ForecastPoint(
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        value=123.0,
        confidence=confidence,
    )


def test_forecast_point_is_immutable_and_validates_confidence() -> None:
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    point = _point(start)

    with pytest.raises(FrozenInstanceError):
        point.value = 456.0  # type: ignore[misc]
    with pytest.raises(ValueError, match="confidence"):
        _point(start, confidence=1.1)


def test_forecast_series_rejects_overlapping_points() -> None:
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    first = _point(start)
    second = ForecastPoint(
        starts_at=start + timedelta(minutes=30),
        ends_at=start + timedelta(hours=2),
        value=200.0,
        confidence=0.7,
    )

    with pytest.raises(ValueError, match="must not overlap"):
        ForecastSeries(
            forecast_id="pv-v1",
            kind=ForecastKind.PV_POWER,
            source="pv-source",
            created_at=start - timedelta(minutes=5),
            expires_at=start + timedelta(hours=3),
            unit="W",
            points=(first, second),
        )


def test_forecast_series_expiry_is_explicit() -> None:
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    series = ForecastSeries(
        forecast_id="price-v1",
        kind=ForecastKind.ENERGY_PRICE,
        source="price-source",
        created_at=start - timedelta(minutes=5),
        expires_at=start + timedelta(hours=2),
        unit="EUR/kWh",
        points=(_point(start),),
    )

    assert not series.is_expired_at(start + timedelta(hours=1))
    assert series.is_expired_at(start + timedelta(hours=2))


def test_forecast_set_rejects_duplicate_ids_and_filters_by_kind() -> None:
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    pv = ForecastSeries(
        forecast_id="pv-v1",
        kind=ForecastKind.PV_POWER,
        source="pv-source",
        created_at=start - timedelta(minutes=5),
        expires_at=start + timedelta(hours=2),
        unit="W",
        points=(_point(start),),
    )

    with pytest.raises(ValueError, match="only once"):
        ForecastSet(series=(pv, pv))

    forecast_set = ForecastSet(series=(pv,))
    assert forecast_set.by_kind(ForecastKind.PV_POWER) == (pv,)
    assert forecast_set.by_kind(ForecastKind.HOUSEHOLD_LOAD) == ()
