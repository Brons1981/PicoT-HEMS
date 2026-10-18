from datetime import UTC, datetime, timedelta

import pytest

from picot_energy_devices.ev_sessions import EVSessionManager
from picot_energy_devices.runtime import ev_poll_once


class VehicleRig:
    def __init__(self, tmp_path):
        self.now = datetime(2026, 10, 18, 4, tzinfo=UTC)
        self.manager = EVSessionManager(
            tmp_path / "vehicle.db", power_entity="sensor.ev", switch_entity="switch.ev",
            vehicle_state_entity="sensor.bmw_state", now=lambda: self.now,
        )
        self.commands = []
        self.manager.action({"action": "save_profile", "expected_power_w": 2300,
                             "expected_duration_seconds": 3600})
        self.manager.action({"action": "start_now"})

    def tick(self, value, *, age=0, switch="on", power=2300, seconds=1, changed=None):
        self.now += timedelta(seconds=seconds)
        return self.manager.tick(
            measured_at=self.now, power_w=power, switch_state=switch,
            set_switch=self.commands.append, vehicle_state=value,
            vehicle_changed_at=self.now - timedelta(seconds=age),
            switch_changed_at=changed,
        )["sessions"][-1]


def test_vehicle_end_stops_owned_plug_and_preserves_reason(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    result = rig.tick("chargingended", power=2)
    assert not rig.commands
    result = rig.tick("chargingended", power=2, seconds=59)
    assert not rig.commands
    result = rig.tick("chargingended", power=2)
    assert rig.commands == [False]
    assert result["vehicle_completion_at"]
    result = rig.tick("chargingended", switch="off", power=0)
    assert result["state"] == "completed"
    assert result["completion_reason"] == "vehicle_charging_ended"
    # A vehicle ended event says nothing about reaching 100% or estimated kWh.
    assert result["remaining_energy_wh"] > 0
    assert not any(key.startswith("vehicle_") for key in rig.manager.snapshot()["session"])


@pytest.mark.parametrize("value,age", [
    ("chargingended", 301), ("unavailable", 0), ("unknown", 0),
    ("chargingended", -10),
    ("chargingpaused", 0), ("charginginterrupted", 0), ("chargingerror", 0),
    ("chargingdisrupted", 0), ("nocharging", 0),
])
def test_unreliable_or_interrupted_state_does_not_complete(tmp_path, value, age):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    result = rig.tick(value, age=age)
    assert not rig.commands
    assert not result.get("vehicle_completion_at")


def test_previous_session_end_does_not_end_new_session(tmp_path):
    rig = VehicleRig(tmp_path)
    result = rig.tick("chargingended")
    assert not result.get("vehicle_completion_at")
    assert not rig.commands


def test_plug_off_is_not_vehicle_completion(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    result = rig.tick("chargingended", switch="off", power=0)
    assert result["state"] == "interrupted"
    assert not result.get("vehicle_completion_at")


def test_deadline_remains_hard_even_if_bmw_says_charging(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.now += timedelta(hours=1)
    rig.tick("chargingactive")
    assert rig.commands == [False]
    result = rig.tick("chargingended", switch="off", power=0)
    assert result["completion_reason"] == "scheduled_deadline"


def test_restart_preserves_current_session_active_evidence(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.manager = EVSessionManager(
        tmp_path / "vehicle.db", power_entity="sensor.ev", switch_entity="switch.ev",
        vehicle_state_entity="sensor.bmw_state", now=lambda: rig.now,
    )
    rig.tick("chargingended", power=2)
    rig.tick("chargingended", power=2, seconds=60)
    assert rig.commands == [False]


def test_sensor_change_does_not_reuse_active_evidence(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.manager.vehicle_state_entity = "sensor.other_vehicle"
    result = rig.tick("chargingended")
    assert not result.get("vehicle_completion_at")
    assert not rig.commands


def test_disabled_vehicle_sensor_cannot_complete(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.manager.vehicle_state_entity = ""
    rig.tick("chargingactive")
    result = rig.tick("chargingended")
    assert not result.get("vehicle_completion_at")
    assert not rig.commands


def test_runtime_reads_vehicle_state_and_survives_unavailable_sensor(tmp_path):
    rig = VehicleRig(tmp_path)

    class Client:
        vehicle = "chargingactive"

        def state(self, entity):
            if entity == "sensor.bmw_state":
                if self.vehicle is None:
                    raise OSError("HA unavailable")
                return {"state": self.vehicle, "last_changed": rig.now.isoformat()}
            return {"state": "2300" if entity == "sensor.ev" else "on",
                    "last_updated": rig.now.isoformat(),
                    "last_changed": "2026-10-18T04:00:00+00:00",
                    "attributes": {"unit_of_measurement": "W"}}

        def set_ev_switch(self, entity, enabled):
            rig.commands.append(enabled)

        def publish_ev_session(self, snapshot):
            pass

    client = Client()
    ev_poll_once(rig.manager, client)
    client.vehicle = None
    rig.now += timedelta(seconds=1)
    ev_poll_once(rig.manager, client)
    assert not rig.commands
    client.vehicle = "chargingactive"
    rig.now += timedelta(seconds=1)
    ev_poll_once(rig.manager, client)
    client.vehicle = "chargingended"
    rig.now += timedelta(seconds=1)
    ev_poll_once(rig.manager, client)
    assert not rig.commands
    rig.now += timedelta(seconds=60)
    ev_poll_once(rig.manager, client)
    assert rig.commands == [False]


@pytest.mark.parametrize("terminal", [False, True])
def test_manual_and_already_completed_sessions_auto_off(tmp_path, terminal):
    rig = VehicleRig(tmp_path)
    state = rig.manager.load()
    session = state["sessions"][-1]
    session.update(state="completed" if terminal else "recognized", confirmed=False,
                   owns_switch=False, direct_start_authorized=False)
    rig.manager.save(state)
    # Low power avoids creating a new recognized session for the terminal case.
    rig.tick("chargingactive", power=500)
    rig.tick("chargingended", power=2)
    assert not rig.commands
    rig.tick("chargingended", power=2, seconds=60)
    assert rig.commands == [False]
    result = rig.tick("chargingended", switch="off", power=0)
    assert result["completion_reason"] == "vehicle_charging_ended"


def test_timer_survives_restart_without_restart_of_countdown(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.tick("chargingended", power=2)
    rig.now += timedelta(seconds=30)
    rig.manager = EVSessionManager(
        tmp_path / "vehicle.db", power_entity="sensor.ev", switch_entity="switch.ev",
        vehicle_state_entity="sensor.bmw_state", now=lambda: rig.now,
    )
    rig.tick("chargingended", power=2, seconds=30)
    assert rig.commands == [False]


@pytest.mark.parametrize("value", ["chargingactive", "unknown", "unavailable", "chargingpaused"])
def test_new_activity_or_unavailable_cancels_pending_timer(tmp_path, value):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.tick("chargingended", power=2)
    rig.tick(value, power=2, seconds=30)
    rig.tick(value, power=2, seconds=30)
    assert not rig.commands


def test_new_plug_on_cannot_reuse_old_ended_event(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.tick("chargingended", power=2)
    switched = rig.now + timedelta(seconds=20)
    rig.tick("chargingended", power=2, seconds=60, changed=switched)
    assert not rig.commands


def test_scheduled_deadline_does_not_wait_for_vehicle_timer(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.now += timedelta(seconds=3550)
    rig.tick("chargingended", power=2)
    rig.tick("chargingended", power=2, seconds=49)
    assert rig.commands == [False]
    result = rig.tick("chargingended", switch="off", power=0)
    assert result["completion_reason"] == "scheduled_deadline"


def test_vehicle_stop_retries_until_switch_off_confirmed(tmp_path):
    rig = VehicleRig(tmp_path)
    rig.tick("chargingactive")
    rig.tick("chargingended", power=2)
    rig.tick("chargingended", power=2, seconds=60)
    rig.tick("chargingended", power=2, seconds=9)
    assert rig.commands == [False]
    rig.tick("chargingended", power=2)
    assert rig.commands == [False, False]
    rig.tick("chargingended", switch="off", power=0)
    rig.tick("chargingended", switch="off", power=0, seconds=20)
    assert rig.commands == [False, False]


def test_manually_resumed_session_still_auto_off_on_new_bmw_end(tmp_path):
    rig = VehicleRig(tmp_path)
    state = rig.manager.load()
    state["sessions"][-1].update(manual_pause=True, state="interrupted", command="turn_off",
                                  last_command_at=rig.now.isoformat())
    rig.manager.save(state)
    rig.tick("chargingactive")
    rig.tick("chargingended", power=2)
    rig.tick("chargingended", power=2, seconds=60)
    assert rig.commands == [False]
    rig.tick("chargingended", switch="off", power=0)
    rig.tick("chargingended", switch="off", power=0, seconds=20)
    assert rig.commands == [False]
