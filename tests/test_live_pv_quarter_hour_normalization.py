from __future__ import annotations

from datetime import datetime

import pytest

from picot.addon.live_snapshot_runtime import pv_energy_timeline_from_telemetry


def test_live_pv_is_integrated_onto_canonical_quarter_hour_boundaries() -> None:
    captured_at = datetime.fromisoformat("2026-08-12T10:07:00+00:00")
    event: dict[str, object] = {
        "solcast_today_confidence": 0.8,
        "solcast_today_forecast_points": [
            {"period_start": "2026-08-12T10:00:00+00:00", "pv_estimate": 1.2},
            {"period_start": "2026-08-12T10:30:00+00:00", "pv_estimate": 2.0},
            {"period_start": "2026-08-12T11:00:00+00:00", "pv_estimate": 0.0},
        ],
    }

    timeline = pv_energy_timeline_from_telemetry(
        event,
        sequence=1,
        captured_at=captured_at,
    )

    assert timeline is not None
    assert [(item.starts_at.minute, item.ends_at.minute) for item in timeline.intervals] == [
        (7, 15),
        (15, 30),
        (30, 45),
        (45, 0),
    ]
    assert [item.energy_wh for item in timeline.intervals] == pytest.approx(
        [160.0, 300.0, 500.0, 500.0]
    )
    assert timeline.total_energy_wh == pytest.approx(1460.0)
    assert all(
        item.method_version == "solcast-power-to-quarter-hour-energy-v2"
        for item in timeline.intervals
    )


def test_source_boundary_inside_quarter_does_not_become_planning_boundary() -> None:
    captured_at = datetime.fromisoformat("2026-08-12T10:07:00+00:00")
    event: dict[str, object] = {
        "solcast_today_confidence": 0.7,
        "solcast_today_forecast_points": [
            {"period_start": "2026-08-12T10:00:00+00:00", "pv_estimate": 1.0},
            {"period_start": "2026-08-12T10:20:00+00:00", "pv_estimate": 2.0},
            {"period_start": "2026-08-12T10:50:00+00:00", "pv_estimate": 0.0},
        ],
    }

    timeline = pv_energy_timeline_from_telemetry(
        event,
        sequence=2,
        captured_at=captured_at,
    )

    assert timeline is not None
    boundaries = [timeline.intervals[0].starts_at, *(item.ends_at for item in timeline.intervals)]
    assert datetime.fromisoformat("2026-08-12T10:20:00+00:00") not in boundaries
    assert datetime.fromisoformat("2026-08-12T10:15:00+00:00") in boundaries
    assert datetime.fromisoformat("2026-08-12T10:30:00+00:00") in boundaries
    # 10:15-10:30 integrates 5 minutes at 1 kW plus 10 minutes at 2 kW.
    assert timeline.intervals[1].energy_wh == pytest.approx(416.6666667)
