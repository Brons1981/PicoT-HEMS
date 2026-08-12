from __future__ import annotations

from picot.addon.live_snapshot_runtime import build_live_planning_snapshot


def test_live_snapshot_contains_storage_state_and_pv_energy_timeline() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-12T10:00:00+00:00",
        "grid_power_w": 500.0,
        "goodwe_solar_power_w": 2500.0,
        "zendure_signed_power_w": 1000.0,
        "zendure_soc_percent": 62.0,
        "zendure_observed_at": "2026-08-12T10:00:00+00:00",
        "storage_usable_capacity_wh": 8000.0,
        "solcast_today_confidence": 0.84,
        "solcast_tomorrow_confidence": 0.62,
        "solcast_today_forecast_points": [
            {"period_start": "2026-08-12T10:00:00+00:00", "pv_estimate": 2.0},
            {"period_start": "2026-08-12T10:30:00+00:00", "pv_estimate": 3.0},
            {"period_start": "2026-08-12T11:00:00+00:00", "pv_estimate": 1.0},
        ],
        "solcast_tomorrow_forecast_points": [],
    }

    snapshot = build_live_planning_snapshot(event, sequence=3)

    assert len(snapshot.current_storage_states) == 1
    storage = snapshot.current_storage_states[0]
    assert storage.current_soc == 0.62
    assert storage.usable_capacity_wh == 8000.0
    assert storage.current_stored_energy_wh == 4960.0
    assert snapshot.pv_energy_timeline is not None
    assert snapshot.pv_energy_timeline.total_energy_wh == 2500.0
    assert snapshot.pv_energy_timeline.intervals[0].confidence == 0.84
    assert snapshot.pv_energy_timeline.horizon_start == snapshot.captured_at
    assert snapshot.pv_energy_timeline.horizon_end == snapshot.horizon_end


def test_missing_capacity_does_not_invent_storage_state() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-12T10:00:00+00:00",
        "zendure_soc_percent": 62.0,
        "zendure_observed_at": "2026-08-12T10:00:00+00:00",
        "solcast_today_forecast_points": [],
        "solcast_tomorrow_forecast_points": [],
    }

    snapshot = build_live_planning_snapshot(event, sequence=4)

    assert snapshot.current_storage_states == ()
    assert snapshot.pv_energy_timeline is None
