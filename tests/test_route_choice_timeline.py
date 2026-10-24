"""Offer graphics preserve stored candidate evidence without planning new actions."""

from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_selection import portfolio_fixture

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.v2.route_choice_policy import _summary


@pytest.fixture(scope="module")
def source_and_owner():
    _, owner, _, _, portfolio = portfolio_fixture()
    return portfolio.sources[0], owner


def summarize(source, owner):
    return _summary(source, "Route", owner.starts_at, owner.ends_at, ZoneInfo("UTC"))


def test_offer_timeline_preserves_full_canonical_schedule_and_identity(source_and_owner):
    source, owner = source_and_owner
    schedule = source.window.schedule
    before = source.window
    summary = summarize(source, owner)
    timeline = summary["timeline"]
    assert timeline["candidate_id"] == source.candidate_id
    assert timeline["snapshot_id"] == schedule.snapshot_id
    assert timeline["schedule_id"] == schedule.schedule_id
    assert timeline["starts_at"] == schedule.horizon_start.isoformat()
    assert timeline["ends_at"] == schedule.horizon_end.isoformat()
    assert timeline["total_segments"] == len(schedule.intervals)
    assert timeline["truncated"] is False
    assert [row["intent"] for row in timeline["segments"]] == [
        interval.intent.value for interval in schedule.intervals
    ]
    assert timeline["segments"][0]["starts_at"] == schedule.intervals[0].starts_at.isoformat()
    assert timeline["segments"][-1]["ends_at"] == schedule.intervals[-1].ends_at.isoformat()
    timeline["segments"][0]["intent"] = "tampered"
    assert source.window == before
    assert summarize(source, owner)["timeline"]["segments"][0]["intent"] != "tampered"


def test_identical_charging_windows_do_not_hide_different_remaining_modes(source_and_owner):
    source, owner = source_and_owner
    window = source.window
    # This projection-only check changes a non-owned interval. It does not claim
    # feasibility or admit either schedule; only the stored modes must be visible.
    index = next(i for i, row in enumerate(window.schedule.intervals)
                 if not any(s.starts_at <= row.starts_at < s.ends_at
                            for s in window.main_segments))
    rows = list(window.schedule.intervals)
    assert rows[index].intent is not DailyStorageIntent.STANDBY
    rows[index] = replace(rows[index], intent=DailyStorageIntent.STANDBY)
    other = replace(source, window=replace(window, schedule=replace(
        window.schedule, intervals=tuple(rows))))
    automatic, alternative = summarize(source, owner), summarize(other, owner)
    assert automatic["main_signature"] == alternative["main_signature"]
    assert automatic["windows"] == alternative["windows"]
    assert automatic["timeline"]["segments"] != alternative["timeline"]["segments"]
    assert alternative["timeline"]["segments"][index]["intent"] == "standby"


def test_oversized_timeline_is_bounded_and_declares_missing_coverage(source_and_owner):
    source, owner = source_and_owner
    window = source.window
    intervals = []
    for row in window.schedule.intervals:
        step = (row.ends_at - row.starts_at) / 100
        intervals.extend(replace(row, starts_at=row.starts_at + step * i,
                                 ends_at=row.starts_at + step * (i + 1)) for i in range(100))
    large = replace(source, window=replace(window, schedule=replace(
        window.schedule, intervals=tuple(intervals))))
    timeline = summarize(large, owner)["timeline"]
    assert len(timeline["segments"]) == 512
    assert timeline["truncated"] is True
    assert timeline["total_segments"] == len(intervals)
    assert timeline["segments"][-1]["ends_at"] < timeline["ends_at"]
