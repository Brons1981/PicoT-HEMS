from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picot_energy_devices.ev_sessions import EVSessionManager

POWER = "sensor.shellyplugsg3_d885ac1e8c94_vermogen"
SWITCH = "switch.shellyplugsg3_d885ac1e8c94"


class Rig:
    def __init__(self, path: Path):
        self.now = datetime(2026, 10, 10, 10, tzinfo=UTC)
        self.manager = EVSessionManager(
            path, power_entity=POWER, switch_entity=SWITCH, now=lambda: self.now
        )
        self.commands = []

    def tick(self, power=2300, switch="on", seconds=1):
        self.now += timedelta(seconds=seconds)
        return self.manager.tick(
            measured_at=self.now if power is not None else None,
            power_w=power,
            switch_state=switch,
            set_switch=self.commands.append,
        )

    def recognize(self):
        for _ in range(31):
            view = self.tick()
        return view["sessions"][-1]

    def plan(self, duration=3600):
        session = self.recognize()
        self.tick(0, "off")
        self.manager.action({"action": "verify_resume", "confirmed": True})
        start = self.now + timedelta(seconds=60)
        self.manager.action(
            {
                "action": "plan",
                "session_id": session["session_id"],
                "planned_start": start.isoformat(),
                "expected_power_w": 2000,
                "expected_duration_seconds": duration,
            }
        )
        return start


def test_plug_on_and_above_2000w_recognizes_immediately(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.tick(2000)
    assert not rig.manager.view()["sessions"]
    rig.tick(2300, "off")
    assert not rig.manager.view()["sessions"]
    view = rig.tick(2294)
    session = view["sessions"][-1]
    assert session["expected_power_w"] == 2294
    assert session["delivered_energy_wh"] == 0
    assert session["expected_duration_seconds"] is None
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["session_id"] == session["session_id"]


def test_stale_or_before_switch_on_measurement_does_not_recognize(tmp_path):
    rig = Rig(tmp_path / "db")
    old = rig.now - timedelta(seconds=76)
    rig.manager.tick(measured_at=old, power_w=2300, switch_state="on",
                     set_switch=rig.commands.append)
    assert not rig.manager.view()["sessions"]
    old = rig.now - timedelta(seconds=5)
    rig.manager.tick(measured_at=old, power_w=2300, switch_state="on",
                     switch_changed_at=rig.now, set_switch=rig.commands.append)
    assert not rig.manager.view()["sessions"]
    assert rig.manager.snapshot()["recognition"]["reason"] == "measurement_before_switch_on"
    rig.tick(2300)
    assert len(rig.manager.view()["sessions"]) == 1


def test_pauses_and_tail_remain_one_session(tmp_path):
    rig = Rig(tmp_path / "db")
    first = rig.recognize()["session_id"]
    for _ in range(80):
        rig.tick(0)
    rig.tick(1800)
    assert len(rig.manager.view()["sessions"]) == 1
    for _ in range(301):
        rig.tick(0)
    session = rig.manager.view()["sessions"][0]
    assert session["session_id"] == first
    assert session["state"] == "completed"


def test_off_preserves_plan_and_restart_does_not_start_early(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.tick(0, "off")
    new = EVSessionManager(
        tmp_path / "db", power_entity=POWER, switch_entity=SWITCH, now=lambda: rig.now
    )
    assert new.view()["sessions"][-1]["state"] == "planned"
    assert new.snapshot()["session"]["remaining_energy_wh"] == 2000
    assert rig.commands == []
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [True]
    rig.tick(2000, "on")
    assert rig.manager.view()["sessions"][-1]["state"] == "active"


def test_resume_verification_is_required(tmp_path):
    rig = Rig(tmp_path / "db")
    session = rig.recognize()
    rig.tick(0, "off")
    with pytest.raises(ValueError, match="hervattest"):
        rig.manager.action(
            {
                "action": "plan",
                "session_id": session["session_id"],
                "planned_start": (rig.now + timedelta(hours=1)).isoformat(),
                "expected_power_w": 2000,
                "expected_duration_seconds": 3600,
            }
        )


def test_cancellation_removes_future_demand_and_never_starts(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    session = rig.manager.view()["sessions"][-1]
    rig.manager.action({"action": "cancel", "session_id": session["session_id"]})
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == []
    assert rig.manager.snapshot()["session"]["state"] == "cancelled"


def test_missing_readings_do_not_complete_session_or_invent_energy(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.recognize()
    before = rig.manager.view()["sessions"][-1]["delivered_energy_wh"]
    for _ in range(400):
        rig.tick(None)
    session = rig.manager.view()["sessions"][-1]
    assert session["state"] == "active"
    assert session["delivered_energy_wh"] == before
    rig.tick()
    assert rig.manager.view()["sessions"][-1]["measurement_complete"] is False


def test_end_time_stops_owned_session_and_waits_for_confirmation(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan(duration=60)
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2000, "on")
    rig.now = start + timedelta(seconds=60)
    rig.tick(2000, "on")
    assert rig.commands == [True, False]
    assert rig.manager.view()["sessions"][-1]["state"] != "completed"
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "completed"


def test_repeated_report_does_not_integrate_twice(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.recognize()
    report = rig.now
    rig.tick()
    before = rig.manager.view()["sessions"][-1]["delivered_energy_wh"]
    rig.manager.tick(
        measured_at=report, power_w=2000, switch_state="on", set_switch=rig.commands.append
    )
    assert rig.manager.view()["sessions"][-1]["delivered_energy_wh"] == before


def test_manual_off_does_not_fight_user_and_explicit_resume_restarts(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2000, "on")
    rig.tick(0, "off")
    for _ in range(15):
        rig.tick(0, "off")
    assert rig.commands == [True]
    rig.manager.action({"action": "resume"})
    rig.tick(0, "off")
    assert rig.commands == [True, True]


def test_failed_command_retries_without_losing_plan(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start

    def fail(_enabled):
        raise OSError("HA service unavailable")

    rig.manager.tick(measured_at=rig.now, power_w=0, switch_state="off", set_switch=fail)
    assert rig.manager.view()["sessions"][-1]["error"] == "HA service unavailable"
    assert rig.manager.view()["sessions"][-1]["state"] == "planned"
    rig.tick(0, "off", seconds=5)
    assert rig.commands == []
    rig.tick(0, "off", seconds=5)
    assert rig.commands == [True]


def test_energy_is_integrated_from_immediate_recognition(tmp_path):
    rig = Rig(tmp_path / "db")
    session = rig.recognize()
    assert session["delivered_energy_wh"] == pytest.approx(2300 * 30 / 3600)
    assert session["expected_duration_seconds"] is None
    assert session["uncertainty"] == "duration_unknown"


def test_planned_start_allows_unchanged_zero_meter_but_not_unknown_switch(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start
    rig.tick(None, "unavailable")
    assert rig.commands == []
    rig.tick(None, "off")
    assert rig.commands == [True]


def test_restart_after_deadline_never_starts_expired_plan(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan(duration=60)
    rig.now = start + timedelta(seconds=61)
    rig.tick(0, "off")
    assert rig.commands == []
    session = rig.manager.view()["sessions"][-1]
    assert session["state"] == "completed"
    assert session["completion_reason"] == "scheduled_deadline"
    assert session["delivered_energy_wh"] < 100


def test_switch_change_cannot_reuse_live_session_or_resume_verification(tmp_path):
    rig = Rig(tmp_path / "db")
    rig.plan()
    with pytest.raises(ValueError, match="Annuleer"):
        EVSessionManager(tmp_path / "db", power_entity=POWER, switch_entity="switch.other")


def test_cancel_owned_run_turns_off_and_waits_for_switch_ack(tmp_path):
    rig = Rig(tmp_path / "db")
    start = rig.plan()
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2000, "on")
    session = rig.manager.view()["sessions"][-1]
    rig.manager.action({"action": "cancel", "session_id": session["session_id"]})
    rig.tick(2000, "on", seconds=10)
    assert rig.commands == [True, False]
    assert rig.manager.view()["sessions"][-1]["state"] != "cancelled"
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "cancelled"


def test_explicit_cancel_also_stops_a_manually_started_recognized_session(tmp_path):
    rig = Rig(tmp_path / "db")
    session = rig.recognize()
    rig.manager.action({"action": "cancel", "session_id": session["session_id"]})
    rig.tick(2000, "on")
    assert rig.commands == [False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "cancelled"
