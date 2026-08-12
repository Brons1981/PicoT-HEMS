from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from picot.addon.history_store import HistoryStore
from picot.addon.household_load_forecaster import HouseholdLoadForecaster
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


def _timeline(start: datetime) -> PVEnergyTimeline:
    first_end = start + timedelta(minutes=30)
    second_end = first_end + timedelta(minutes=30)
    return PVEnergyTimeline(
        timeline_id="pv-test",
        created_at=start,
        horizon_start=start,
        horizon_end=second_end,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=start,
                ends_at=first_end,
                energy_wh=0.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("pv-1",),
            ),
            PVEnergyTimelineInterval(
                starts_at=first_end,
                ends_at=second_end,
                energy_wh=0.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("pv-2",),
            ),
        ),
    )


def test_weighted_profile_uses_recent_matching_quarter_hours(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    history = HistoryStore(path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    for days_ago, power in ((1, 1000.0), (2, 800.0), (3, 600.0)):
        for minute_offset in (0, 15):
            measured = now - timedelta(days=days_ago) + timedelta(minutes=minute_offset)
            history.append(
                {
                    "event": "picot_live_planning_snapshot",
                    "captured_at": measured.isoformat(),
                    "household_load_w": power,
                }
            )

    forecaster = HouseholdLoadForecaster(history=history)
    forecast = forecaster.forecast(
        captured_at=now,
        pv_timeline=_timeline(now),
        current_household_load_w=500.0,
        sequence=1,
    )

    assert forecast.historical_source_reference == "picot_history:last_14_days"
    assert forecast.intervals[0].expected_energy_wh > 300.0
    assert forecast.intervals[0].confidence >= 0.6
    assert forecast.method_version == "weighted-quarter-hour-profile-v1"


def test_no_history_falls_back_to_current_load_with_low_confidence(tmp_path: Path) -> None:
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    forecaster = HouseholdLoadForecaster(history=HistoryStore(tmp_path / "empty.jsonl"))

    forecast = forecaster.forecast(
        captured_at=now,
        pv_timeline=_timeline(now),
        current_household_load_w=400.0,
        sequence=2,
    )

    assert forecast.historical_source_reference == "fallback:current_household_load"
    assert forecast.expected_energy_wh == 400.0
    assert forecast.confidence == 0.10


def test_runtime_observation_is_added_after_history_load(tmp_path: Path) -> None:
    now = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    forecaster = HouseholdLoadForecaster(history=HistoryStore(tmp_path / "empty.jsonl"))
    forecaster.observe(measured_at=now, household_load_w=1200.0)

    forecast = forecaster.forecast(
        captured_at=now,
        pv_timeline=_timeline(now),
        current_household_load_w=1200.0,
        sequence=3,
    )

    assert forecast.intervals[0].expected_energy_wh == 600.0
    assert forecast.intervals[0].confidence == 0.20
