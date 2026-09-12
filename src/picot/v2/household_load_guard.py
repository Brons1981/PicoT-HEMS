"""Bounded, measured household-load protection; no appliance or vendor control."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Literal, Protocol

from picot.v2.contracts import HouseholdLoadForecast, HouseholdLoadForecastInterval

WINDOW = timedelta(minutes=5)
MAXIMUM_SAMPLE_HOLD = timedelta(seconds=180)
PROJECTION = timedelta(minutes=15)
METHOD_VERSION = "measured-household-excess-15m:v1"


class _Observation(Protocol):
    @property
    def sampled_at(self) -> datetime: ...

    @property
    def power_w(self) -> float: ...


@dataclass(frozen=True, slots=True)
class HouseholdLoadGuardAssessment:
    active: bool
    quality: Literal["reliable", "held", "unknown"]
    extra_power_w: float
    assessed_at: datetime
    last_reliable_at: datetime | None = None
    release_started_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _Integral:
    times: tuple[datetime, ...]
    values: tuple[float, ...]
    coverage: tuple[float, ...]
    powers: tuple[float, ...]
    valid: tuple[bool, ...]

    def at(self, when: datetime) -> tuple[float, float]:
        index = bisect_right(self.times, when) - 1
        if index < 0:
            return 0.0, 0.0
        seconds = (when - self.times[index]).total_seconds()
        return (
            self.values[index] + self.powers[index] * seconds,
            self.coverage[index] + (seconds if self.valid[index] else 0.0),
        )


def _integral(
    observations: Sequence[_Observation],
    baseline: HouseholdLoadForecast,
    assessed_at: datetime,
) -> _Integral:
    # Missing or non-finite readings never establish that an active load stopped.
    observations = tuple(sorted(
        (item for item in observations if item.sampled_at <= assessed_at),
        key=lambda item: item.sampled_at,
    ))
    intervals = baseline.intervals
    boundaries = sorted({
        point
        for item in observations
        for point in (item.sampled_at, item.sampled_at + MAXIMUM_SAMPLE_HOLD)
        if point <= assessed_at
    } | {
        point for interval in intervals
        for point in (interval.starts_at, interval.ends_at)
        if point <= assessed_at
    } | {assessed_at})
    samples = [item.sampled_at for item in observations]
    starts = [item.starts_at for item in intervals]
    values: list[float] = []
    coverage: list[float] = []
    powers: list[float] = []
    valid: list[bool] = []
    total = covered = 0.0
    for index, when in enumerate(boundaries):
        if index:
            duration = (when - boundaries[index - 1]).total_seconds()
            total += powers[-1] * duration
            covered += duration if valid[-1] else 0.0
        sample_index = bisect_right(samples, when) - 1
        interval_index = bisect_right(starts, when) - 1
        usable = False
        power = 0.0
        if sample_index >= 0 and interval_index >= 0:
            sample = observations[sample_index]
            interval = intervals[interval_index]
            usable = (
                when < sample.sampled_at + MAXIMUM_SAMPLE_HOLD
                and when < interval.ends_at
                and isfinite(sample.power_w)
                and sample.power_w >= 0.0
                and isfinite(interval.expected_energy_wh)
            )
            if usable:
                baseline_w = interval.expected_energy_wh * 3600.0 / (
                    interval.ends_at - interval.starts_at
                ).total_seconds()
                power = sample.power_w - baseline_w
        values.append(total)
        coverage.append(covered)
        powers.append(power)
        valid.append(usable)
    return _Integral(tuple(boundaries), tuple(values), tuple(coverage),
                     tuple(powers), tuple(valid))


def assess_household_load_guard(
    *,
    observations: Sequence[_Observation],
    baseline: HouseholdLoadForecast | None,
    assessed_at: datetime,
    previous: HouseholdLoadGuardAssessment | None = None,
) -> HouseholdLoadGuardAssessment:
    """Replay reliable sample windows, or continue from a preserved assessment.

    Baseline must cover the observation period being assessed (including the
    preceding five minutes), and must not already contain this overlay. Supply
    ``previous`` when truncating history: unknown data must not clear protection.
    Release is confirmed at measurement/poll timestamps, never interpolated.
    """
    if previous is not None and previous.assessed_at > assessed_at:
        raise ValueError("previous assessment must not be in the future")
    if baseline is None:
        if previous is None:
            return HouseholdLoadGuardAssessment(False, "unknown", 0.0, assessed_at)
        return replace(previous, quality="unknown", extra_power_w=0.0,
                       assessed_at=assessed_at, release_started_at=None)
    start = baseline.intervals[0].starts_at if baseline.intervals else assessed_at
    # Keep one prior observation to establish the held value at baseline start.
    ordered = sorted((item for item in observations if item.sampled_at <= assessed_at),
                     key=lambda item: item.sampled_at)
    first = max(0, bisect_right([item.sampled_at for item in ordered], start) - 1)
    ordered = ordered[first:]
    integral = _integral(ordered, baseline, assessed_at)
    state = previous or HouseholdLoadGuardAssessment(False, "unknown", 0.0, start)
    events = sorted({item.sampled_at for item in ordered
                     if start <= item.sampled_at <= assessed_at
                     and (previous is None or item.sampled_at > previous.assessed_at)}
                    | {assessed_at})
    for when in events:
        value, covered = integral.at(when)
        prior_value, prior_covered = integral.at(when - WINDOW)
        reliable = covered - prior_covered >= WINDOW.total_seconds() - 1e-6
        if reliable:
            extra = max(0.0, (value - prior_value) / WINDOW.total_seconds())
            active = state.active or extra >= 500.0
            release = state.release_started_at
            # A gap between assessments breaks continuous evidence of low load.
            if state.last_reliable_at is None or when - state.last_reliable_at > WINDOW:
                release = None
            sample_index = bisect_right(
                [item.sampled_at for item in ordered], when,
            ) - 1
            baseline_interval = next((
                interval for interval in baseline.intervals
                if interval.starts_at <= when < interval.ends_at
            ), None)
            if (baseline_interval is None and baseline.intervals
                    and when == baseline.intervals[-1].ends_at):
                baseline_interval = baseline.intervals[-1]
            current_extra: float | None = None
            if sample_index >= 0 and baseline_interval is not None:
                sample = ordered[sample_index]
                if (when < sample.sampled_at + MAXIMUM_SAMPLE_HOLD
                        and isfinite(sample.power_w) and sample.power_w >= 0.0):
                    baseline_w = baseline_interval.expected_energy_wh * 3600.0 / (
                        baseline_interval.ends_at - baseline_interval.starts_at
                    ).total_seconds()
                    current_extra = sample.power_w - baseline_w
            if active and current_extra is not None and current_extra <= 250.0:
                release = release or when
                if when - release >= WINDOW:
                    active = False
                    release = None
            else:
                release = None
            state = HouseholdLoadGuardAssessment(
                active, "reliable", extra if active else 0.0, when, when, release,
            )
        else:
            held = (state.last_reliable_at is not None
                    and when - state.last_reliable_at <= WINDOW)
            state = replace(state, quality="held" if held else "unknown",
                            extra_power_w=state.extra_power_w if held else 0.0,
                            assessed_at=when, release_started_at=None)
    return state


def apply_household_load_guard(
    forecast: HouseholdLoadForecast,
    assessment: HouseholdLoadGuardAssessment,
) -> HouseholdLoadForecast:
    """Add observed excess only to the next fifteen minutes of the base forecast."""
    if not assessment.active or assessment.extra_power_w <= 0.0:
        return forecast
    if assessment.quality == "unknown":
        return forecast
    start, end = assessment.assessed_at, assessment.assessed_at + PROJECTION
    intervals: list[HouseholdLoadForecastInterval] = []
    for interval in forecast.intervals:
        if interval.ends_at <= start or interval.starts_at >= end:
            intervals.append(interval)
            continue
        boundaries = sorted({interval.starts_at, interval.ends_at}
                            | {point for point in (start, end)
                               if interval.starts_at < point < interval.ends_at})
        duration = (interval.ends_at - interval.starts_at).total_seconds()
        for left, right in zip(boundaries, boundaries[1:], strict=False):
            seconds = (right - left).total_seconds()
            energy = interval.expected_energy_wh * seconds / duration
            overlay = start <= left < end
            if overlay:
                energy += assessment.extra_power_w * seconds / 3600.0
            seed = f"{interval.interval_id}|{left}|{right}|{energy}|{METHOD_VERSION}"
            identifier = sha256(seed.encode()).hexdigest()[:16]
            intervals.append(replace(
                interval, interval_id=f"household-load-interval-{identifier}",
                starts_at=left, ends_at=right, expected_energy_wh=energy,
                source_reference=(f"{interval.source_reference};measured-excess:"
                                  f"{assessment.assessed_at.isoformat()}"
                                  if overlay else interval.source_reference),
                method_version=METHOD_VERSION if overlay else interval.method_version,
            ))
    seed = "|".join(item.interval_id for item in intervals)
    return replace(forecast, forecast_id=f"household-load-{sha256(seed.encode()).hexdigest()[:16]}",
                   intervals=tuple(intervals))
