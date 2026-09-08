"""Fixed comparison periods and content identity, independent of route selection."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_selection import snapshot_for_main

from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.daily_pv_comparison import (
    DailyPVComparisonBasis,
    DailyPVReferenceInterval,
    compare_daily_pv,
)


def owner_for(source):
    return DailyChargeAssignment("battery", source.captured_at.date(), "UTC", source.captured_at)


def actual(interval, value):
    return replace(
        interval,
        evidence_type="ACTUAL",
        pv_energy_wh=value,
        forecast_range_status="unavailable",
        forecast_lower_energy_wh=None,
        forecast_central_energy_wh=None,
        forecast_upper_energy_wh=None,
        actual_evidence_ids=(f"observed:{interval.interval_id}:{value}",),
        conversion_method_version="test-actual-energy",
    )


@pytest.mark.parametrize(
    "values,boundary",
    [
        ((800.0, 800.0), "at_or_below_lower"),
        ((700.0, 700.0), "at_or_below_lower"),
        ((1000.0, 1000.0), "within_bounds"),
        ((1100.0, 1100.0), "above_central"),
    ],
)
def test_exact_cumulative_lower_and_central_boundaries(values, boundary):
    source = snapshot_for_main()
    basis = DailyPVComparisonBasis.capture(source, owner_for(source))
    timeline = replace(
        source.pv_energy_timeline,
        intervals=tuple(
            actual(i, values[n]) if n < 2 else i
            for n, i in enumerate(source.pv_energy_timeline.intervals)
        ),
    )
    result = compare_daily_pv(basis, timeline, at=source.captured_at + timedelta(hours=1))
    assert result.status == "complete"
    assert result.boundary == boundary
    assert result.actual_wh == sum(values)
    assert result.lower_wh == 1600
    assert result.central_wh == 2000


def test_poll_time_forecast_updates_and_roundtrip_do_not_change_evidence():
    source = snapshot_for_main()
    basis = DailyPVComparisonBasis.capture(source, owner_for(source))
    recovered = DailyPVComparisonBasis.from_payload(json.loads(json.dumps(basis.to_payload())))
    assert recovered == basis
    assert recovered.basis_id == basis.basis_id
    timeline = replace(
        source.pv_energy_timeline,
        intervals=(
            actual(source.pv_energy_timeline.intervals[0], 1200),
            *source.pv_energy_timeline.intervals[1:],
        ),
    )
    first = compare_daily_pv(basis, timeline, at=source.captured_at + timedelta(minutes=30))
    second = compare_daily_pv(recovered, timeline, at=source.captured_at + timedelta(minutes=35))
    assert first == second
    corrected = replace(
        timeline,
        intervals=(actual(source.pv_energy_timeline.intervals[0], 1300), *timeline.intervals[1:]),
    )
    assert compare_daily_pv(basis, corrected, at=second.ends_at).evidence_id != first.evidence_id


def test_missing_or_overlapping_intervals_never_become_complete_by_count():
    source = snapshot_for_main()
    basis = DailyPVComparisonBasis.capture(source, owner_for(source))
    second = actual(source.pv_energy_timeline.intervals[1], 1400)
    for intervals in ((second,),):
        result = compare_daily_pv(
            basis,
            replace(source.pv_energy_timeline, intervals=intervals),
            at=source.captured_at + timedelta(hours=1),
        )
        assert result.status == "partial"
        assert result.actual_wh is None
        assert result.boundary is None
        assert result.starts_at == source.captured_at

    with pytest.raises(ValueError, match="overlap"):
        replace(source.pv_energy_timeline, intervals=(second, second))


def test_late_start_excludes_already_started_forecast_interval():
    source = snapshot_for_main()
    at = source.captured_at + timedelta(minutes=7)
    source = replace(
        source,
        captured_at=at,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            captured_at=at,
        ),
    )
    basis = DailyPVComparisonBasis.capture(source, owner_for(source))
    assert basis.intervals[0].starts_at == at.replace(minute=30)
    result = compare_daily_pv(basis, source.pv_energy_timeline, at=at.replace(minute=45))
    assert result.status == "no_closed_interval"


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 29), 23), (datetime(2026, 10, 25), 25)])
def test_reference_respects_delivery_day_and_survives_timezone_roundtrip(day, hours):
    start = day.replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    owner = DailyChargeAssignment(
        "battery", start.date(), "Europe/Amsterdam", start - timedelta(hours=2)
    )
    intervals = tuple(
        DailyPVReferenceInterval(
            owner.starts_at + timedelta(minutes=30 * n),
            owner.starts_at + timedelta(minutes=30 * (n + 1)),
            1,
            2,
            (f"forecast:{n}",),
        )
        for n in range(hours * 2)
    )
    basis = DailyPVComparisonBasis(
        owner.assignment_id, "snapshot", owner.created_at, owner.starts_at, owner.ends_at, intervals
    )
    recovered = DailyPVComparisonBasis.from_payload(json.loads(json.dumps(basis.to_payload())))
    assert basis.basis_id == recovered.basis_id
    assert len(recovered.intervals) == hours * 2
    assert recovered.day_ends_at - recovered.day_starts_at == timedelta(hours=hours)


def test_reference_rejects_gaps_and_after_the_fact_capture():
    at = datetime(2026, 9, 8, tzinfo=UTC)
    interval = DailyPVReferenceInterval(at, at + timedelta(hours=1), 1, 2, ("forecast",))
    with pytest.raises(ValueError, match="precede"):
        DailyPVComparisonBasis(
            "owner", "snapshot", at + timedelta(minutes=1), at, interval.ends_at, (interval,)
        )
    with pytest.raises(ValueError, match="contiguous"):
        DailyPVComparisonBasis(
            "owner",
            "snapshot",
            at,
            at,
            at + timedelta(hours=3),
            (
                interval,
                replace(
                    interval, starts_at=at + timedelta(hours=2), ends_at=at + timedelta(hours=3)
                ),
            ),
        )
