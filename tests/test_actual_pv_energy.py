from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from picot.addon.actual_pv_energy import (
    ACTUAL_PV_METHOD_VERSION,
    actual_pv_interval_from_history,
    prepend_actual_pv_evidence,
)
from picot.addon.history_store import HistoryStore
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)

UTC = timezone.utc


def _append_goodwe(history: HistoryStore, at: datetime, power_w: float) -> None:
    history.append(
        {
            "event": "picot_goodwe_snapshot",
            "layer": "pv_actual",
            "status": "available",
            "solar_power_w": power_w,
            "observed_at": at.isoformat(),
        }
    )


def _current_event(at: datetime, power_w: float) -> dict[str, object]:
    return {
        "goodwe_status": "available",
        "goodwe_solar_power_w": power_w,
        "telemetry_interval_seconds": 5,
        "telemetry_updated_at": at.isoformat(),
    }


def test_actual_current_quarter_integrates_sample_hold_energy(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    quarter = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    captured = quarter + timedelta(minutes=10)
    _append_goodwe(history, quarter - timedelta(seconds=5), 1000.0)
    for seconds in range(5, 600, 5):
        power_w = 1000.0 if seconds < 300 else 2000.0
        _append_goodwe(history, quarter + timedelta(seconds=seconds), power_w)

    interval = actual_pv_interval_from_history(
        history=history,
        event=_current_event(captured, 2000.0),
        captured_at=captured,
        sequence=7,
    )

    assert interval is not None
    assert interval.starts_at == quarter
    assert interval.ends_at == captured
    assert interval.energy_wh == pytest.approx(250.0)
    assert interval.evidence_type is PVEnergyEvidenceType.ACTUAL
    assert interval.method_version == ACTUAL_PV_METHOD_VERSION


def test_actual_pv_fails_closed_on_long_measurement_gap(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    quarter = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    captured = quarter + timedelta(minutes=10)
    _append_goodwe(history, quarter - timedelta(seconds=5), 1000.0)
    _append_goodwe(history, quarter + timedelta(minutes=1), 1000.0)

    interval = actual_pv_interval_from_history(
        history=history,
        event=_current_event(captured, 1000.0),
        captured_at=captured,
        sequence=8,
    )

    assert interval is None


def test_actual_elapsed_energy_prepends_without_replacing_future_forecast(
    tmp_path: Path,
) -> None:
    history = HistoryStore(tmp_path / "history.jsonl")
    quarter = datetime(2026, 8, 13, 10, 0, tzinfo=UTC)
    captured = quarter + timedelta(minutes=5)
    future_end = quarter + timedelta(minutes=15)
    _append_goodwe(history, quarter - timedelta(seconds=5), 900.0)
    for seconds in range(5, 300, 5):
        _append_goodwe(history, quarter + timedelta(seconds=seconds), 900.0)

    future = PVEnergyTimeline(
        timeline_id="pv-live",
        created_at=captured,
        horizon_start=captured,
        horizon_end=future_end,
        intervals=(
            PVEnergyTimelineInterval(
                starts_at=captured,
                ends_at=future_end,
                energy_wh=200.0,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=0.8,
                evidence_ids=("solcast-1",),
                method_version="solcast-test",
            ),
        ),
    )

    combined = prepend_actual_pv_evidence(
        timeline=future,
        history=history,
        event=_current_event(captured, 900.0),
        captured_at=captured,
        sequence=9,
    )

    assert combined.horizon_start == quarter
    assert len(combined.intervals) == 2
    assert combined.intervals[0].evidence_type is PVEnergyEvidenceType.ACTUAL
    assert combined.intervals[0].energy_wh == pytest.approx(75.0)
    assert combined.intervals[1] == future.intervals[0]
