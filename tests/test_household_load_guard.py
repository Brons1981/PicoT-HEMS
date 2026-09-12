"""Behavior checks for measured demand without device identity or duration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from picot.v2.contracts import HouseholdLoadForecast, HouseholdLoadForecastInterval
from picot.v2.household_load_guard import (
    apply_household_load_guard,
    assess_household_load_guard,
)

START = datetime(2026, 9, 12, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Reading:
    sampled_at: datetime
    power_w: float


def _forecast() -> HouseholdLoadForecast:
    return HouseholdLoadForecast(
        "base", "run", "snapshot", tuple(
            HouseholdLoadForecastInterval(
                str(index), START + timedelta(minutes=index * 15),
                START + timedelta(minutes=(index + 1) * 15),
                100.0, 1.0, "history", "baseline",
            ) for index in range(8)
        ), False, None,
    )


def _readings(powers: list[float]) -> list[Reading]:
    return [Reading(START + timedelta(minutes=index), power)
            for index, power in enumerate(powers)]


def test_short_peak_does_not_activate_and_sustained_load_does() -> None:
    readings = _readings([400.0] * 5 + [2400.0] + [400.0] * 5)
    peak = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=6),
    )
    assert not peak.active  # One minute contributes only 400 W excess average.
    active = assess_household_load_guard(
        observations=_readings([2400.0] * 11), baseline=_forecast(),
        assessed_at=START + timedelta(minutes=10),
    )
    assert active.active
    assert active.quality == "reliable"
    assert active.extra_power_w == 2000.0


def test_time_weighting_and_future_readings() -> None:
    # Many clustered readings must not outweigh elapsed seconds.
    readings = [Reading(START, 400.0),
                Reading(START + timedelta(seconds=150), 400.0)]
    readings += [Reading(START + timedelta(seconds=240 + index), 2400.0)
                 for index in range(60)]
    readings.append(Reading(START + timedelta(minutes=6), 10000.0))
    result = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=5),
    )
    assert result.quality == "reliable"
    assert not result.active


def test_brief_dryer_pause_keeps_active_then_reliable_release() -> None:
    readings = _readings([2400.0] * 10 + [160.0] * 2 + [2400.0] * 3 + [400.0] * 15)
    pause = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=12),
    )
    assert pause.active
    recent_stop = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=19),
    )
    assert recent_stop.active  # Five reliable low-load minutes not confirmed yet.
    stopped = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=20),
    )
    assert not stopped.active
    assert stopped.quality == "reliable"


def test_gap_retains_only_five_minutes_then_reports_unknown() -> None:
    readings = _readings([2400.0] * 11)
    active = assess_household_load_guard(
        observations=readings, baseline=_forecast(),
        assessed_at=START + timedelta(minutes=10),
    )
    held = assess_household_load_guard(
        observations=readings, baseline=_forecast(), previous=active,
        assessed_at=START + timedelta(minutes=14),
    )
    assert held.active and held.quality == "held"
    assert held.extra_power_w == 2000.0
    unknown = assess_household_load_guard(
        observations=readings, baseline=_forecast(), previous=held,
        assessed_at=START + timedelta(minutes=16),
    )
    assert unknown.active and unknown.quality == "unknown"
    assert unknown.extra_power_w == 0.0
    assert apply_household_load_guard(_forecast(), unknown) == _forecast()


def test_projection_splits_quarters_and_conserves_other_energy() -> None:
    baseline = _forecast()
    assessment = assess_household_load_guard(
        observations=_readings([2400.0] * 11), baseline=baseline,
        assessed_at=START + timedelta(minutes=10),
    )
    projected = apply_household_load_guard(baseline, assessment)
    assert sum(item.expected_energy_wh for item in projected.intervals) == 1300.0
    assert baseline.intervals[0].expected_energy_wh == 100.0
    assert projected.intervals[0].ends_at == START + timedelta(minutes=10)
    assert projected.intervals[0].expected_energy_wh == 100.0 * 10 / 15
    assert projected.intervals[-1] == baseline.intervals[-1]
    after = next(item for item in projected.intervals
                 if item.starts_at == START + timedelta(minutes=25))
    assert after.expected_energy_wh == 100.0 * 5 / 15


def test_missing_baseline_is_unknown() -> None:
    assessment = assess_household_load_guard(
        observations=_readings([2400.0] * 11), baseline=None,
        assessed_at=START + timedelta(minutes=10),
    )
    assert assessment.quality == "unknown"
    assert assessment.extra_power_w == 0.0
