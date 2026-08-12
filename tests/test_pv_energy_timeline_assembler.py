from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.pv_energy_timeline import PVEnergyEvidenceType
from picot.planning.pv_energy_timeline_assembler import (
    ActualPVEnergyInterval,
    ForecastPVPowerInterval,
    assemble_pv_energy_timeline,
)


def test_actual_replaces_elapsed_forecast_and_future_uses_forecast() -> None:
    interval_start = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    captured_at = interval_start + timedelta(minutes=10)
    horizon_end = captured_at + timedelta(minutes=20)

    timeline = assemble_pv_energy_timeline(
        timeline_id="pv-timeline-1",
        captured_at=captured_at,
        horizon_end=horizon_end,
        actual_intervals=(
            ActualPVEnergyInterval(
                starts_at=interval_start,
                ends_at=captured_at,
                energy_wh=120.0,
                confidence=1.0,
                evidence_ids=("actual:pv-energy",),
            ),
        ),
        forecast_intervals=(
            ForecastPVPowerInterval(
                starts_at=captured_at,
                ends_at=horizon_end,
                average_power_w=1800.0,
                confidence=0.8,
                evidence_ids=("forecast:pv-power",),
                method_version="avg-power-v1",
            ),
        ),
    )

    assert timeline.horizon_start == interval_start
    assert timeline.intervals[0].evidence_type is PVEnergyEvidenceType.ACTUAL
    assert timeline.intervals[0].energy_wh == 120.0
    assert timeline.intervals[1].evidence_type is PVEnergyEvidenceType.FORECAST
    assert timeline.intervals[1].energy_wh == pytest.approx(600.0)
    assert timeline.total_energy_wh == pytest.approx(720.0)


def test_forecast_power_conversion_uses_interval_duration() -> None:
    starts_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    interval = ForecastPVPowerInterval(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=15),
        average_power_w=2000.0,
        confidence=0.9,
        evidence_ids=("forecast:pv-power",),
        method_version="avg-power-v1",
    )

    assert interval.energy_wh == pytest.approx(500.0)


def test_actual_must_end_exactly_at_capture_time() -> None:
    starts_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    captured_at = starts_at + timedelta(minutes=10)
    horizon_end = captured_at + timedelta(minutes=20)

    with pytest.raises(ValueError, match="end exactly"):
        assemble_pv_energy_timeline(
            timeline_id="pv-timeline-2",
            captured_at=captured_at,
            horizon_end=horizon_end,
            actual_intervals=(
                ActualPVEnergyInterval(
                    starts_at=starts_at,
                    ends_at=captured_at - timedelta(minutes=1),
                    energy_wh=100.0,
                    confidence=1.0,
                    evidence_ids=("actual:pv-energy",),
                ),
            ),
            forecast_intervals=(
                ForecastPVPowerInterval(
                    starts_at=captured_at,
                    ends_at=horizon_end,
                    average_power_w=1000.0,
                    confidence=0.8,
                    evidence_ids=("forecast:pv-power",),
                    method_version="avg-power-v1",
                ),
            ),
        )


def test_forecast_must_start_at_capture_time_to_avoid_double_counting() -> None:
    starts_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    captured_at = starts_at + timedelta(minutes=10)
    horizon_end = captured_at + timedelta(minutes=20)

    with pytest.raises(ValueError, match="start exactly"):
        assemble_pv_energy_timeline(
            timeline_id="pv-timeline-3",
            captured_at=captured_at,
            horizon_end=horizon_end,
            actual_intervals=(
                ActualPVEnergyInterval(
                    starts_at=starts_at,
                    ends_at=captured_at,
                    energy_wh=100.0,
                    confidence=1.0,
                    evidence_ids=("actual:pv-energy",),
                ),
            ),
            forecast_intervals=(
                ForecastPVPowerInterval(
                    starts_at=starts_at,
                    ends_at=horizon_end,
                    average_power_w=1000.0,
                    confidence=0.8,
                    evidence_ids=("forecast:pv-power",),
                    method_version="avg-power-v1",
                ),
            ),
        )
