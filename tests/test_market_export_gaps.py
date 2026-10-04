from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.market_execution import MarketExecutionProgress
from picot.v2.market_export_measurement import bounded_market_export, measured_market_export
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, PowerHistorySnapshot

START = datetime(2026, 10, 4, 17, 15, 52, tzinfo=UTC)


def telemetry(*, duration=1.0, gap_role="battery_discharge", export=1200, gaps=1):
    series = []
    for role, power in (("battery_discharge", 2400), ("grid_export", export)):
        points = [PowerHistoryPoint(START, power, "anchor")]
        if gap_role in (role, "both"):
            for index in range(gaps):
                begin = START + timedelta(seconds=5 + 3 * index)
                points.extend((PowerHistoryPoint(begin, float("nan"), "gap"),
                    PowerHistoryPoint(begin + timedelta(seconds=duration), power, "resumed")))
        series.append(PowerHistorySeries(role, role, "sensor." + role, "positive", tuple(points)))
    return PowerHistorySnapshot(START, START + timedelta(seconds=60), "available", None,
        tuple(series))


@pytest.mark.parametrize("role", ["battery_discharge", "grid_export", "both"])
def test_gap_energy_is_separate_and_physical_upper_bound_is_conservative(role):
    h = telemetry(gap_role=role)
    assert measured_market_export(h, h.starts_at, h.ends_at) is None
    result = bounded_market_export(h, h.starts_at, h.ends_at, maximum_power_w=2400)
    assert result.measured_export_wh == pytest.approx(1200 * 59 / 3600)
    assert result.estimated_export_wh == pytest.approx(1200 / 3600)
    upper_power = 1200 if role == "battery_discharge" else 2400
    assert result.uncertainty_wh == pytest.approx(upper_power / 3600)


@pytest.mark.parametrize("duration", [0.986637, 2.0])
def test_recovered_short_gaps_are_allowed(duration):
    h = telemetry(duration=duration)
    assert bounded_market_export(h, h.starts_at, h.ends_at, maximum_power_w=2400) is not None


def test_total_uncertainty_is_bounded_even_for_many_short_gaps():
    h = telemetry(gap_role="both", gaps=8)
    assert bounded_market_export(h, h.starts_at, h.ends_at, maximum_power_w=2400) is None


def test_gap_cannot_create_export_when_grid_reports_zero():
    h = telemetry(export=0)
    result = bounded_market_export(h, h.starts_at, h.ends_at, maximum_power_w=2400)
    assert result.measured_export_wh == result.estimated_export_wh == result.uncertainty_wh == 0


def test_negative_power_missing_anchor_and_unrecovered_tail_are_rejected():
    h = telemetry()
    for points in ((PowerHistoryPoint(START, -1, "negative"),), (),
        (PowerHistoryPoint(START, 2400, "anchor"),
            PowerHistoryPoint(START + timedelta(seconds=59), float("nan"), "open"))):
        invalid = replace(h, series=(replace(h.series[0], points=points), h.series[1]))
        assert bounded_market_export(invalid, h.starts_at, h.ends_at, maximum_power_w=2400) is None


def test_legacy_progress_defaults_and_invalid_estimates():
    assert MarketExecutionProgress("legacy").export_uncertainty_wh == 0
    with pytest.raises(ValueError):
        MarketExecutionProgress("invalid", started_at=START, measured_export_wh=1,
            estimated_export_wh=2, export_uncertainty_wh=1)
