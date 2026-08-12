from __future__ import annotations

from picot.addon.live_snapshot_runtime import (
    build_live_planning_snapshot,
    household_state_from_telemetry,
    snapshot_log_event,
)


def _event() -> dict[str, object]:
    return {
        "telemetry_updated_at": "2026-08-12T10:00:00+00:00",
        "grid_power_w": 500.0,
        "goodwe_solar_power_w": 2500.0,
        "zendure_signed_power_w": 1000.0,
        # Presentation/mirror fields may coexist in the telemetry event. They
        # must never be consulted by the snapshot bridge.
        "sensor.picot_fake_power": 9999.0,
    }


def test_one_live_poll_becomes_one_atomic_vendor_independent_snapshot() -> None:
    snapshot = build_live_planning_snapshot(_event(), sequence=7)

    assert snapshot.household_state.grid_power_w == 500.0
    assert snapshot.household_state.pv_power_w == 2500.0
    assert snapshot.household_state.battery_power_w == 1000.0
    assert snapshot.household_state.household_load_w == 2000.0
    assert snapshot.versions.household_state == 7
    assert "sensor.picot" not in repr(snapshot)
    assert "goodwe" not in repr(snapshot).lower()
    assert "zendure" not in repr(snapshot).lower()


def test_missing_source_dimension_remains_unknown_instead_of_invented() -> None:
    event = _event()
    event["goodwe_solar_power_w"] = None

    state = household_state_from_telemetry(event)

    assert state.pv_power_w is None
    assert state.household_load_w is None


def test_snapshot_log_contains_domain_values_not_source_entities() -> None:
    record = snapshot_log_event(build_live_planning_snapshot(_event(), sequence=1))

    assert record["status"] == "observation_only"
    assert record["grid_power_w"] == 500.0
    assert "entity_id" not in record
    assert "source_entity" not in record
