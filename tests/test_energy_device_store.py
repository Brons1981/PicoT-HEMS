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

    for offset, power, energy in (
        (0, 1000.0, 10_000.0),
        (30, 1000.0, 10_008.0),
        (60, 0.0, 10_016.0),
        (120, 1200.0, 10_016.0),
        (150, 1200.0, 10_026.0),
        (180, 0.0, 10_036.0),
    ):
        store.record_observation(
            device.device_id,
            DeviceObservation(
                observed_at=now + timedelta(seconds=offset),
                power_w=power,
                energy_meter_wh=energy,
            ),
        )

    card = store.catalog()["cards"][0]  # type: ignore[index]
    assert card["profile_status"] == "ready"
    assert card["completed_session_count"] == 2
    assert card["expected_duration_seconds"] == pytest.approx(60.0)
    assert card["expected_energy_wh"] == pytest.approx(18.0)
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
