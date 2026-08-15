from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import PVEnergyTimelineInterval
from picot.v2.pv_cumulative_evidence import (
    CUMULATIVE_EVIDENCE_METHOD_VERSION,
    build_pv_cumulative_evidence,
)
from picot.v2.pv_deviation import evaluate_pv_energy_deviation


EVALUATED_AT = datetime(2026, 8, 15, 10, 5, tzinfo=UTC)


def _interval_pair(
    *,
    interval_id: str,
    starts_at: datetime,
    forecast_wh: float,
    lower_wh: float,
    upper_wh: float,
    actual_wh: float,
    confidence: float,
):
    ends_at = starts_at + timedelta(minutes=30)
    forecast = PVEnergyTimelineInterval(
        interval_id=f"forecast-{interval_id}",
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=forecast_wh,
        evidence_type="FORECAST",
        confidence=confidence,
        actual_evidence_ids=(),
        forecast_evidence_ids=(f"solcast-{interval_id}",),
        conversion_method_version=(
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
        forecast_lower_energy_wh=lower_wh,
        forecast_central_energy_wh=forecast_wh,
        forecast_upper_energy_wh=upper_wh,
        forecast_range_status="available",
        forecast_range_source_fields=(
            "pv_estimate10",
            "pv_estimate",
            "pv_estimate90",
        ),
        forecast_range_method_version=(
            "solcast-pv-estimate-range-average-kw-30m:v1"
        ),
    )
    actual = PVEnergyTimelineInterval(
        interval_id=f"actual-{interval_id}",
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=actual_wh,
        evidence_type="ACTUAL",
        confidence=1.0,
        actual_evidence_ids=(f"goodwe-{interval_id}",),
        forecast_evidence_ids=(f"solcast-{interval_id}",),
        conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
        ),
    )
    return evaluate_pv_energy_deviation(
        forecast=forecast,
        actual=actual,
        evaluated_at=EVALUATED_AT,
    )


def test_cumulative_evidence_uses_only_aligned_actual_intervals() -> None:
    first = _interval_pair(
        interval_id="0800",
        starts_at=datetime(2026, 8, 15, 8, 0, tzinfo=UTC),
        forecast_wh=400.0,
        lower_wh=300.0,
        upper_wh=500.0,
        actual_wh=250.0,
        confidence=0.2,
    )
    second = _interval_pair(
        interval_id="0830",
        starts_at=datetime(2026, 8, 15, 8, 30, tzinfo=UTC),
        forecast_wh=500.0,
        lower_wh=400.0,
        upper_wh=650.0,
        actual_wh=600.0,
        confidence=0.8,
    )

    evidence = build_pv_cumulative_evidence(
        (first, second),
        closed_interval_count=3,
        evaluated_at=EVALUATED_AT,
    )

    assert evidence.coverage_status == "partial"
    assert evidence.closed_interval_count == 3
    assert evidence.assessed_interval_count == 2
    assert evidence.gap_interval_count == 1
    assert evidence.coverage_ratio == pytest.approx(2 / 3)
    assert evidence.starts_at == first.starts_at
    assert evidence.ends_at == second.ends_at

    assert evidence.forecast_central_energy_wh == 900.0
    assert evidence.actual_energy_wh == 850.0
    assert evidence.net_deviation_energy_wh == -50.0
    assert evidence.absolute_net_deviation_energy_wh == 50.0
    assert (
        evidence.total_absolute_interval_deviation_energy_wh
        == 250.0
    )
    assert evidence.deviation_percent == pytest.approx(-50 / 900 * 100)
    assert evidence.percentage_status == "available"

    assert evidence.forecast_lower_energy_wh == 700.0
    assert evidence.forecast_upper_energy_wh == 1150.0
    assert evidence.forecast_range_status == "available"
    assert evidence.range_assessment == "within_range"
    assert evidence.range_distance_wh == 0.0
    assert evidence.range_assessed_interval_count == 2

    assert evidence.below_range_interval_count == 1
    assert evidence.within_range_interval_count == 1
    assert evidence.above_range_interval_count == 0
    assert evidence.unavailable_range_interval_count == 0
    assert evidence.interval_deviation_ids == (
        first.deviation_id,
        second.deviation_id,
    )
    assert evidence.method_version == CUMULATIVE_EVIDENCE_METHOD_VERSION
    assert evidence.method_version == (
        "pv-cumulative-deviation:"
        "aligned-closed-intervals:v1"
    )


def test_cumulative_evidence_does_not_invent_missing_range_bounds() -> None:
    result = _interval_pair(
        interval_id="0900",
        starts_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        forecast_wh=500.0,
        lower_wh=400.0,
        upper_wh=650.0,
        actual_wh=450.0,
        confidence=0.4,
    )
    result = result.__class__(
        **{
            field: getattr(result, field)
            for field in result.__dataclass_fields__
            if field not in {
                "forecast_lower_energy_wh",
                "forecast_upper_energy_wh",
                "forecast_range_status",
                "range_assessment",
                "range_distance_wh",
            }
        },
        forecast_lower_energy_wh=None,
        forecast_upper_energy_wh=None,
        forecast_range_status="unavailable",
        range_assessment="unavailable",
        range_distance_wh=None,
    )

    evidence = build_pv_cumulative_evidence(
        (result,),
        closed_interval_count=1,
        evaluated_at=EVALUATED_AT,
    )

    assert evidence.forecast_range_status == "unavailable"
    assert evidence.forecast_lower_energy_wh is None
    assert evidence.forecast_upper_energy_wh is None
    assert evidence.range_assessment == "unavailable"
    assert evidence.range_distance_wh is None
    assert evidence.range_assessed_interval_count == 0
    assert evidence.unavailable_range_interval_count == 1
