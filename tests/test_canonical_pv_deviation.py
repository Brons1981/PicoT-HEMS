from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from picot.addon.canonical_pv_deviation import (
    CanonicalPVDeviationEvaluator,
    quarter_anchor_event,
    runtime_monitor_fields,
)
from picot.addon.history_store import HistoryStore
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

UTC = timezone.utc


def _goodwe(history: HistoryStore, at: datetime, power_w: float) -> None:
    history.append(
        {
            "event": "picot_goodwe_snapshot",
            "status": "available",
            "solar_power_w": power_w,
            "observed_at": at.isoformat(),
        }
    )


def _anchor(
    history: HistoryStore,
    *,
    anchored_at: datetime,
    starts_at: datetime,
    expected_wh: float,
) -> None:
    history.append(
        {
            "event": "picot_pv_forecast_quarter_anchor",
            "observed_at": anchored_at.isoformat(),
            "anchored_at": anchored_at.isoformat(),
            "interval_start": starts_at.isoformat(),
            "interval_end": (starts_at + timedelta(minutes=15)).isoformat(),
            "expected_energy_wh": expected_wh,
            "forecast_evidence_ids": ["solcast:test"],
            "forecast_method_version": "solcast-quarter-test",
        }
    )


def test_anchor_freezes_next_full_forecast_quarter() -> None:
    captured = datetime(2026, 8, 13, 10, 7, tzinfo=UTC)
    start = datetime(2026, 8, 13, 10, 15, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    timeline = PVEnergyTimeline(
        timeline_id="pv",
        created_at=captured,
        horizon_start=captured,
        horizon_end=end,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=captured,
                ends_at=start,
                energy_wh=40.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("solcast:partial",),
                method_version="solcast-v2",
            ),
            PVEnergyTimelineInterval(
                starts_at=start,
                ends_at=end,
                energy_wh=250.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("solcast:quarter",),
                method_version="solcast-v2",
            ),
        ),
    )

    event = quarter_anchor_event(timeline=timeline, captured_at=captured)

    assert event is not None
    assert event["interval_start"] == start.isoformat()
    assert event["expected_energy_wh"] == 250.0
    assert event["observed_at"] == captured.isoformat()


def test_material_completed_quarter_routes_through_runtime_monitor(
    tmp_path: Path,
) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    start = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    _anchor(
        history,
        anchored_at=start - timedelta(seconds=5),
        starts_at=start,
        expected_wh=500.0,
    )
    for seconds in range(-5, 15 * 60 + 1, 5):
        _goodwe(history, start + timedelta(seconds=seconds), 1000.0)

    evaluator = CanonicalPVDeviationEvaluator(history=history)
    result = evaluator.evaluate(captured_at=end + timedelta(seconds=5))

    assert result is not None
    assert result.expected_energy_wh == pytest.approx(500.0)
    assert result.actual_energy_wh == pytest.approx(250.0)
    assert result.deviation_percent == pytest.approx(-50.0)
    assert result.threshold_crossed is True
    monitor = runtime_monitor_fields(result, observed_at=end + timedelta(seconds=5))
    assert monitor["canonical_pv_material_classification"] == "material_replan"
    assert monitor["canonical_pv_replan_signal"] == "fresh_snapshot_required"
    assert monitor["canonical_pv_fresh_snapshot_required"] is True


def test_within_tolerance_is_authoritative_but_non_material(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    start = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    _anchor(
        history,
        anchored_at=start - timedelta(seconds=5),
        starts_at=start,
        expected_wh=250.0,
    )
    for seconds in range(-5, 15 * 60 + 1, 5):
        _goodwe(history, start + timedelta(seconds=seconds), 1000.0)

    result = CanonicalPVDeviationEvaluator(history=history).evaluate(
        captured_at=end + timedelta(seconds=5)
    )

    assert result is not None
    assert result.deviation_percent == pytest.approx(0.0)
    assert result.threshold_crossed is False
    monitor = runtime_monitor_fields(result, observed_at=end + timedelta(seconds=5))
    assert monitor["canonical_pv_material_classification"] == "non_material"
    assert monitor["canonical_pv_replan_signal"] == "none"


def test_missing_actual_coverage_fails_closed(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    start = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    end = start + timedelta(minutes=15)
    _anchor(
        history,
        anchored_at=start - timedelta(seconds=5),
        starts_at=start,
        expected_wh=300.0,
    )
    _goodwe(history, start - timedelta(seconds=5), 1200.0)
    _goodwe(history, start + timedelta(minutes=10), 1200.0)

    result = CanonicalPVDeviationEvaluator(history=history).evaluate(
        captured_at=end + timedelta(seconds=5)
    )

    assert result is None
