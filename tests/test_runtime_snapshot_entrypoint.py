from __future__ import annotations

from picot.addon import runtime_snapshot_entrypoint


def test_runtime_evidence_composition_appends_one_planning_snapshot() -> None:
    event: dict[str, object] = {
        "telemetry_updated_at": "2026-08-12T10:00:00+00:00",
        "grid_power_w": 500.0,
        "goodwe_solar_power_w": 2500.0,
        "zendure_signed_power_w": 1000.0,
    }

    records = runtime_snapshot_entrypoint.telemetry_evidence_events_with_snapshot(event)

    snapshots = [
        record
        for record in records
        if record.get("event") == "picot_live_planning_snapshot"
    ]
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "observation_plus_storage_pv"
    assert snapshots[0]["household_load_w"] == 2000.0
