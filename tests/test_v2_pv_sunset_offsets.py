from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from picot.v2.pv_sunset_offsets import (
    SUNSET_OFFSET_METHOD_VERSION,
    derive_pv_sunset_offsets,
)

from picot.v2.contracts import (
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
PROJECTED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _interval(
    *,
    interval_id: str,
    starts_at: datetime,
    ends_at: datetime,
    evidence_type: str = "FORECAST",
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=ends_at,
        pv_energy_wh=100.0,
        evidence_type=evidence_type,
        confidence=0.5,
        actual_evidence_ids=(
            ("actual-evidence",)
            if evidence_type == "ACTUAL"
            else ()
        ),
        forecast_evidence_ids=(
            ("forecast-evidence",)
            if evidence_type == "FORECAST"
            else ()
        ),
        conversion_method_version="test-conversion:v1",
        forecast_lower_energy_wh=80.0,
        forecast_central_energy_wh=100.0,
        forecast_upper_energy_wh=130.0,
        forecast_range_status="available",
        forecast_range_source_fields=(
            "pv_estimate10",
            "pv_estimate",
            "pv_estimate90",
        ),
        forecast_range_method_version="test-range:v1",
    )


def _timeline() -> PVEnergyTimeline:
    return PVEnergyTimeline(
        timeline_id="pv-timeline-sunset-offsets",
        run_id="run-sunset-offsets",
        snapshot_id="snapshot-sunset-offsets",
        intervals=(
            _interval(
                interval_id="past-forecast",
                starts_at=datetime(2026, 8, 16, 11, 0, tzinfo=UTC),
                ends_at=datetime(2026, 8, 16, 11, 30, tzinfo=UTC),
            ),
            _interval(
                interval_id="future-actual",
                starts_at=datetime(2026, 8, 16, 18, 0, tzinfo=UTC),
                ends_at=datetime(2026, 8, 16, 18, 30, tzinfo=UTC),
                evidence_type="ACTUAL",
            ),
            _interval(
                interval_id="future-forecast-day-one",
                starts_at=datetime(2026, 8, 16, 18, 30, tzinfo=UTC),
                ends_at=datetime(2026, 8, 16, 19, 0, tzinfo=UTC),
            ),
            _interval(
                interval_id="future-forecast-day-two",
                starts_at=datetime(2026, 8, 17, 18, 30, tzinfo=UTC),
                ends_at=datetime(2026, 8, 17, 19, 0, tzinfo=UTC),
            ),
            _interval(
                interval_id="future-forecast-missing-sunset",
                starts_at=datetime(2026, 8, 18, 18, 30, tzinfo=UTC),
                ends_at=datetime(2026, 8, 18, 19, 0, tzinfo=UTC),
            ),
        ),
    )


def test_future_forecast_offsets_use_each_local_dates_sunset() -> None:
    offsets = derive_pv_sunset_offsets(
        timeline=_timeline(),
        sunsets_by_local_date={
            date(2026, 8, 16): datetime(
                2026, 8, 16, 20, 55, tzinfo=AMSTERDAM
            ),
            date(2026, 8, 17): datetime(
                2026, 8, 17, 20, 53, tzinfo=AMSTERDAM
            ),
        },
        projected_at=PROJECTED_AT,
    )

    assert offsets == {
        "future-forecast-day-one": pytest.approx(-10.0),
        "future-forecast-day-two": pytest.approx(-8.0),
    }
    assert "past-forecast" not in offsets
    assert "future-actual" not in offsets
    assert "future-forecast-missing-sunset" not in offsets


def test_sunset_offset_derivation_is_deterministic_and_immutable() -> None:
    timeline = _timeline()
    original = timeline.intervals
    sunsets = {
        date(2026, 8, 16): datetime(
            2026, 8, 16, 20, 55, tzinfo=AMSTERDAM
        )
    }

    first = derive_pv_sunset_offsets(
        timeline=timeline,
        sunsets_by_local_date=sunsets,
        projected_at=PROJECTED_AT,
    )
    second = derive_pv_sunset_offsets(
        timeline=timeline,
        sunsets_by_local_date=dict(reversed(tuple(sunsets.items()))),
        projected_at=PROJECTED_AT,
    )

    assert first == second
    assert timeline.intervals == original
    assert SUNSET_OFFSET_METHOD_VERSION == "pv-sunset-offset:interval-midpoint:v1"


@pytest.mark.parametrize(
    ("projected_at", "sunset"),
    (
        (datetime(2026, 8, 16, 12, 0), None),
        (
            PROJECTED_AT,
            datetime(2026, 8, 16, 20, 55),
        ),
    ),
)
def test_sunset_offset_inputs_require_timezone_awareness(
    projected_at: datetime,
    sunset: datetime | None,
) -> None:
    sunsets = (
        {}
        if sunset is None
        else {date(2026, 8, 16): sunset}
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        derive_pv_sunset_offsets(
            timeline=_timeline(),
            sunsets_by_local_date=sunsets,
            projected_at=projected_at,
        )
