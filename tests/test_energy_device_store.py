from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot_energy_devices.contracts import DeviceObservation
from picot_energy_devices.store import EnergyDeviceStore


def test_device_is_immediately_discoverable_and_sessions_build_profile(tmp_path: Path) -> None:
    now = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3", now=lambda: now)
    device = store.add_device(
        name="Droger",
        power_entity_id="sensor.droger_vermogen",
        energy_entity_id="sensor.droger_energie",
        active_threshold_w=20.0,
    )

    initial = store.catalog()
    assert initial["observer_only"] is True
    assert initial["planning_authority"] is False
    assert initial["cards"][0]["profile_status"] == "learning"  # type: ignore[index]

    base = now
    for offset, power, energy in (
        (0, 1000.0, 10_000.0),
        (30, 1000.0, 10_008.0),
        (60, 0.0, 10_016.0),
        (120, 1200.0, 10_016.0),
        (150, 1200.0, 10_026.0),
        (180, 0.0, 10_036.0),
    ):
        now = base + timedelta(seconds=offset)
        store.record_observation(
            device.device_id,
            DeviceObservation(
                observed_at=now,
                power_w=power,
                energy_meter_wh=energy,
            ),
        )

        if offset in (0, 120):
            store.start_recording(device.device_id, "Standaard")
        elif offset in (60, 180):
            store.finish_recording(device.device_id)

    card = store.catalog()["cards"][0]  # type: ignore[index]
    assert card["profile_status"] == "ready"
    assert card["completed_session_count"] == 2
    assert card["expected_duration_seconds"] == pytest.approx(60.0)
    assert card["expected_energy_wh"] == pytest.approx((1000 + 1200) / 120)
    assert card["confidence"] > 0.0


def test_disabling_device_removes_card_but_keeps_database(tmp_path: Path) -> None:
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3")
    device = store.add_device(name="EV", power_entity_id="sensor.ev_power")
    store.disable_device(device.device_id)

    assert store.catalog()["cards"] == []
    assert store.database_size_bytes() > 0


def test_registry_accepts_sensor_sources_only(tmp_path: Path) -> None:
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3")
    with pytest.raises(ValueError, match="must be a sensor"):
        store.add_device(name="Onveilig", power_entity_id="switch.droger")


def test_manual_recording_keeps_pauses_and_survives_restart(tmp_path: Path) -> None:
    base = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    now = base
    path = tmp_path / "devices.sqlite3"
    store = EnergyDeviceStore(path, now=lambda: now, maximum_sample_gap_seconds=60)
    d = store.add_device(name="Vaatwasser", power_entity_id="sensor.dishwasher")
    store.record_observation(d.device_id, DeviceObservation(now, 0))
    store.start_recording(d.device_id, "Eco")
    with pytest.raises(ValueError, match="al een opname"):
        store.start_recording(d.device_id, "Tweede")
    def clock() -> datetime:
        return now
    for minute, power in enumerate([1000, 5, 5, 5, 5, 2000, 4], 1):
        now = base + timedelta(minutes=minute)
        store.record_observation(d.device_id, DeviceObservation(now, power))
        if minute == 3:
            store = EnergyDeviceStore(path, now=clock, maximum_sample_gap_seconds=60)
    assert len(store.recording_list(d.device_id)) == 1
    store.finish_recording(d.device_id)
    rec = store.recording_list(d.device_id)[0]
    assert rec["duration_seconds"] == 420
    assert rec["missing_seconds"] == 0
    assert rec["observed_energy_wh"] == pytest.approx(3020 / 60)
    assert len(store.recording_detail(int(rec["recording_id"]))["samples"]) == 8
    with pytest.raises(ValueError, match="geen opname"):
        store.finish_recording(d.device_id)
    store.rename_recording(int(rec["recording_id"]), "Eco 50°")
    assert store.recording_list(d.device_id)[0]["name"] == "Eco 50°"
    store.delete_recording(int(rec["recording_id"]))
    assert store.recording_list(d.device_id) == []
    assert store.catalog()["cards"][0]["completed_session_count"] == 0


def test_missing_data_is_not_zero_and_partial_energy_is_not_a_profile(tmp_path: Path) -> None:
    now = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    base = now
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3", now=lambda: now,
                              maximum_sample_gap_seconds=60)
    d = store.add_device(name="Test", power_entity_id="sensor.test")
    store.record_observation(d.device_id, DeviceObservation(now, 3600))
    store.start_recording(d.device_id, "Met meetuitval")
    now = base + timedelta(seconds=10)
    store.record_unavailable(d.device_id, "Sensor onbereikbaar", observed_at=now)
    now = base + timedelta(seconds=20)
    store.record_observation(d.device_id, DeviceObservation(now, 3600))
    now = base + timedelta(seconds=120)
    store.record_observation(d.device_id, DeviceObservation(now, 3600))
    now = base + timedelta(seconds=130)
    store.finish_recording(d.device_id)
    rec = store.recording_list(d.device_id)[0]
    assert rec["missing_seconds"] == 110
    assert rec["observed_energy_wh"] == 20
    assert store.catalog()["cards"][0]["expected_energy_wh"] is None
    assert store.recording_detail(int(rec["recording_id"]))["samples"][1]["power_w"] is None


def test_no_automatic_sessions_and_legacy_history_can_be_cleared(tmp_path: Path) -> None:
    now = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3", now=lambda: now)
    d = store.add_device(name="Test", power_entity_id="sensor.test")
    for seconds, power in [(0, 2000), (10, 4), (20, 1000), (30, 0)]:
        store.record_observation(
            d.device_id, DeviceObservation(now+timedelta(seconds=seconds), power)
        )
    assert store.recording_list(d.device_id) == []
    with store._connect() as con:
        con.execute("INSERT INTO sessions(device_id,starts_at,ends_at,duration_seconds,"
                    "energy_wh,average_power_w,peak_power_w,sample_count) VALUES(?,?,?,?,?,?,?,?)",
                    (d.device_id, now.isoformat(), now.isoformat(), 10, 2, 720, 1000, 2))
    card = store.catalog()["cards"][0]
    assert card["legacy_session_count"] == 1
    assert card["completed_session_count"] == 0
    store.clear_legacy_sessions(d.device_id)
    assert store.catalog()["cards"][0]["legacy_session_count"] == 0


def test_empty_recording_and_cancel_do_not_create_a_learned_profile(tmp_path: Path) -> None:
    now = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)
    store = EnergyDeviceStore(tmp_path / "devices.sqlite3", now=lambda: now)
    d = store.add_device(name="Test", power_entity_id="sensor.test")
    store.start_recording(d.device_id, "Geen metingen")
    with pytest.raises(ValueError, match="Rond de opname"):
        store.disable_device(d.device_id)
    now += timedelta(seconds=60)
    store.finish_recording(d.device_id)
    rec = store.recording_list(d.device_id)[0]
    assert rec["missing_seconds"] == 60
    assert rec["sample_count"] == 0
    assert store.catalog()["cards"][0]["expected_energy_wh"] is None
    store.start_recording(d.device_id, "Annuleren")
    active = store.recording_list(d.device_id)[0]
    store.delete_recording(int(active["recording_id"]))
    store.record_observation(d.device_id, DeviceObservation(now, 2000))
    assert len(store.recording_list(d.device_id)) == 1
    assert store.catalog()["cards"][0]["recording"] is None
