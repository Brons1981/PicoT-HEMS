"""Calendar summaries and out-of-sample model comparison, never planner input."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import fmean, median
from typing import Any

from picot.v2.household_calendar_history import METHOD_VERSION, QUARTER_US
from picot.v2.household_load_forecast import (
    MAXIMUM_HISTORICAL_PERIODS,
    MAXIMUM_LOOKBACK_DAYS,
    MINIMUM_HISTORICAL_PERIODS,
)
from picot.v2.passive_history.calendar import AMSTERDAM, bounds

WEEKDAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
REPORT_DAYS = 112
PROFILE_LOOKBACK_DAYS = 56
MINIMUM_COVERAGE = 0.95
MODELS = ("current_clock_quarter", "same_weekday", "workday_weekend")


def _day_type(weekday: int) -> str:
    return "weekend" if weekday >= 6 else "workday"


def _sample_mean(row: dict[str, Any]) -> float | None:
    if (row["sample_count"] < 2 or row["first_sample_us"] is None
            or row["last_sample_us"] - row["first_sample_us"] < QUARTER_US / 2):
        return None
    return float(row["sample_sum_w"] / row["sample_count"])


def _weighted(values: list[float]) -> float | None:
    """Input newest first, matching the unchanged canonical history weighting."""
    values = values[:MAXIMUM_HISTORICAL_PERIODS]
    if len(values) < MINIMUM_HISTORICAL_PERIODS:
        return None
    oldest_first = list(reversed(values))
    return sum(i * v for i, v in enumerate(oldest_first, 1)) / sum(
        range(1, len(values) + 1)
    )


def _predictions(
    row: dict[str, Any], by_utc: dict[int, dict[str, Any]],
    by_clock: dict[int, list[dict[str, Any]]],
) -> dict[str, float | None]:
    target = date.fromisoformat(row["local_date"])
    baseline: list[float] = []
    for ago in range(1, MAXIMUM_LOOKBACK_DAYS + 1):
        source = by_utc.get(row["start_us"] - ago * 86_400_000_000)
        if source is not None and source["local_date"] < row["local_date"]:
            mean = _sample_mean(source)
            if mean is not None:
                baseline.append(mean)
    alternatives: dict[str, dict[str, list[float]]] = {
        "same_weekday": {}, "workday_weekend": {},
    }
    for source in by_clock[row["clock_quarter"]]:
        source_day = date.fromisoformat(source["local_date"])
        if not 1 <= (target - source_day).days <= PROFILE_LOOKBACK_DAYS:
            continue
        mean = _sample_mean(source)
        if mean is None or source["covered_us"] / QUARTER_US < MINIMUM_COVERAGE:
            continue
        for model, matches in (
            ("same_weekday", source["weekday"] == row["weekday"]),
            ("workday_weekend", _day_type(source["weekday"]) == _day_type(row["weekday"])),
        ):
            if matches:
                alternatives[model].setdefault(source["local_date"], []).append(mean)
    result = {"current_clock_quarter": _weighted(baseline)}
    for model, periods in alternatives.items():
        # Repeated DST quarters form one source period, not two weighted days.
        result[model] = _weighted([fmean(periods[d]) for d in sorted(periods, reverse=True)])
    return {model: None if power is None else power / 4 for model, power in result.items()}


def _summary(days: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [d for d in days if d["usable_for_profile"]]
    energy = [float(d["observed_energy_wh"]) for d in eligible]
    return {
        "days_present": len(days), "eligible_days": len(energy),
        "excluded_days": len(days) - len(energy),
        "mean_observed_energy_wh": fmean(energy) if energy else None,
        "median_observed_energy_wh": median(energy) if energy else None,
        "mean_coverage_fraction": fmean(d["coverage_fraction"] for d in eligible)
        if eligible else None,
    }


def build_calendar_report(db: sqlite3.Connection, *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("calendar report needs an aware timestamp")
    today = now.astimezone(AMSTERDAM).date()
    latest = db.execute("SELECT MAX(local_date) FROM quarter").fetchone()[0]
    latest_day = date.fromisoformat(latest) if latest else today
    first_day = latest_day - timedelta(days=REPORT_DAYS - 1)
    rows = [dict(row) for row in db.execute(
        "SELECT * FROM quarter WHERE local_date>=? ORDER BY start_us LIMIT 12001",
        (first_day.isoformat(),),
    )]
    if len(rows) > 12000:
        raise ValueError("calendar report quarter budget exceeded")
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_clock: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_utc = {row["start_us"]: row for row in rows}
    for row in rows:
        by_day[row["local_date"]].append(row)
        by_clock[row["clock_quarter"]].append(row)
    days: list[dict[str, Any]] = []
    errors: dict[str, list[float]] = {model: [] for model in MODELS}
    for label, quarters in sorted(by_day.items()):
        day = date.fromisoformat(label)
        start, end = bounds(day)
        covered = sum(q["covered_us"] for q in quarters)
        coverage = covered / (end - start)
        comparisons: list[dict[str, Any]] = []
        for q in quarters:
            if day >= today or q["covered_us"] / QUARTER_US < MINIMUM_COVERAGE:
                continue
            predictions = _predictions(q, by_utc, by_clock)
            if any(v is None for v in predictions.values()):
                continue
            # Only observed duration is scored; no invented energy in missing seconds.
            predictions = {
                k: float(v) * q["covered_us"] / QUARTER_US
                for k, v in predictions.items() if v is not None
            }
            comparisons.append({"starts_at_utc": datetime.fromtimestamp(
                q["start_us"] / 1_000_000, UTC).isoformat(),
                "observed_energy_wh": q["energy_wh"], "predicted_energy_wh": predictions})
            for model, value in predictions.items():
                errors[model].append(value - q["energy_wh"])
        days.append({
            "local_date": label, "weekday": day.weekday() + 1,
            "weekday_name": WEEKDAYS[day.weekday()], "day_type": _day_type(day.weekday() + 1),
            "iso_year": day.isocalendar().year, "iso_week": day.isocalendar().week,
            "expected_quarters": (end - start) // QUARTER_US,
            "closed": day < today, "coverage_fraction": coverage,
            "observed_energy_wh": sum(q["energy_wh"] for q in quarters),
            "usable_for_profile": day < today and coverage >= MINIMUM_COVERAGE,
            "sample_count": sum(q["sample_count"] for q in quarters),
            "quarters": quarters, "common_comparison_quarters": len(comparisons),
            "retrospective_comparison": comparisons,
        })
    profiles: dict[str, list[dict[str, Any]]] = {}
    for key in [*WEEKDAYS, "workday", "weekend"]:
        profile = []
        for clock in range(96):
            periods: dict[str, list[float]] = {}
            for q in by_clock[clock]:
                day = date.fromisoformat(q["local_date"])
                matches = key in {WEEKDAYS[q["weekday"] - 1], _day_type(q["weekday"])}
                if (matches and 1 <= (today - day).days <= PROFILE_LOOKBACK_DAYS
                        and q["covered_us"] / QUARTER_US >= MINIMUM_COVERAGE):
                    periods.setdefault(q["local_date"], []).append(
                        q["energy_wh"] * QUARTER_US / q["covered_us"]
                    )
            recent = sorted(periods, reverse=True)[:MAXIMUM_HISTORICAL_PERIODS]
            values = [fmean(periods[d]) for d in recent]
            profile.append({"clock_quarter": clock, "source_days": recent,
                            "period_count": len(values), "expected_energy_wh": _weighted(values)})
        profiles[key] = profile
    checkpoint = db.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
    progress = dict(checkpoint) if checkpoint else {}
    try:
        source_bytes = Path(progress["source"]).stat().st_size if progress else None
    except OSError:
        source_bytes = None
    progress.update(source_bytes=source_bytes, caught_up=(
        bool(progress) and progress.get("offset_bytes") == source_bytes
    ))
    return {
        "schema_version": 1, "observer_only": True, "timezone": "Europe/Amsterdam",
        "method_version": METHOD_VERSION, "generated_at": now.isoformat(),
        "source_progress": progress, "report_days_limit": REPORT_DAYS,
        "all_history_quarters": db.execute("SELECT count(*) FROM quarter").fetchone()[0],
        "minimum_profile_coverage": MINIMUM_COVERAGE, "days": days,
        "weekday_summary": {name: _summary([d for d in days if d["weekday"] == i])
                            for i, name in enumerate(WEEKDAYS, 1)},
        "day_type_summary": {key: _summary([d for d in days if d["day_type"] == key])
                             for key in ("workday", "weekend")},
        "quarter_profiles": profiles,
        "model_comparison": {
            "kind": "retrospective_prior_days_only_not_recorded_planner_forecasts",
            "common_quarters": len(errors[MODELS[0]]),
            "models": {model: {
                "mean_absolute_quarter_error_wh": fmean(abs(v) for v in values)
                if values else None,
                "mean_signed_quarter_error_wh": fmean(values) if values else None,
            } for model, values in errors.items()},
        },
    }
