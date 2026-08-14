from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.household_load_forecast import (
    build_fallback_household_load_forecast,
)

BASE = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
HORIZON_END = BASE + timedelta(hours=36)


def build(
    *,
    starts_at: datetime = BASE,
    horizon_end: datetime = HORIZON_END,
    fallback_power_w: float = 500.0,
):
    return build_fallback_household_load_forecast(
        run_id="run-household-load-builder",
        snapshot_id="snapshot-household-load-builder",
        starts_at=starts_at,
        horizon_end=horizon_end,
        fallback_power_w=fallback_power_w,
    )


def test_fallback_forecast_covers_the_36_hour_horizon() -> None:
    result = build()

    assert result.run_id == "run-household-load-builder"
    assert result.snapshot_id == "snapshot-household-load-builder"
    assert result.fallback_active is True
    assert result.fallback_reason == "insufficient_history"
    assert len(result.intervals) == 144

    first = result.intervals[0]
    last = result.intervals[-1]

    assert first.starts_at == BASE
    assert first.ends_at == BASE + timedelta(minutes=15)
    assert last.ends_at == HORIZON_END


def test_fallback_intervals_are_contiguous_and_explicit() -> None:
    result = build()

    for previous, current in zip(
        result.intervals,
        result.intervals[1:],
        strict=False,
    ):
        assert previous.ends_at == current.starts_at

    assert all(
        interval.ends_at - interval.starts_at
        == timedelta(minutes=15)
        for interval in result.intervals
    )
    assert all(
        interval.expected_energy_wh == pytest.approx(125.0)
        for interval in result.intervals
    )
    assert all(
        interval.confidence == pytest.approx(0.0)
        for interval in result.intervals
    )
    assert all(
        interval.source_reference == "fallback:configured-power"
        for interval in result.intervals
    )
    assert all(
        interval.method_version
        == "constant-power-conservative-fallback:v1"
        for interval in result.intervals
    )


def test_fallback_forecast_is_deterministic() -> None:
    first = build()
    second = build()

    assert first == second


@pytest.mark.parametrize(
    "fallback_power_w",
    (0.0, -0.01),
)
def test_fallback_requires_positive_power(
    fallback_power_w: float,
) -> None:
    with pytest.raises(
        ValueError,
        match="fallback_power_w must be positive",
    ):
        build(fallback_power_w=fallback_power_w)


def test_fallback_requires_a_positive_horizon() -> None:
    with pytest.raises(
        ValueError,
        match="starts_at must be before horizon_end",
    ):
        build(horizon_end=BASE)
