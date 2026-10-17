from datetime import timedelta

import pytest
from test_ev_deadline_request import request
from test_ev_sessions import POWER, SWITCH, Rig

from picot_energy_devices.ev_sessions import EVSessionManager


def prepare(tmp_path):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    start = rig.now + timedelta(hours=1)
    advice = {
        "contract": "energy-device-charging-advice:v1",
        "session_id": demand["session_id"], "request_revision": 1,
        "generated_at": rig.now.isoformat(), "status": "provisional",
        "slots": [{"starts_at": start.isoformat(),
                   "ends_at": (start + timedelta(hours=3)).isoformat(), "energy_wh": 6900}],
    }
    assert rig.manager.receive_advice(advice)
    command = {**advice, "action": "execute_advice"}
    return rig, advice, command, start


def test_accepted_plan_survives_restart_starts_and_stops(tmp_path):
    rig, advice, command, start = prepare(tmp_path)
    rig.manager.action(command)
    rig.manager.action(command)  # retry cannot create another session
    assert len(rig.manager.view()["sessions"]) == 1
    assert rig.manager.snapshot()["storage_support_allowed"] is False
    assert rig.manager.advice_exchange()["request"]["state"] == "accepted"
    assert not rig.manager.receive_advice(advice)
    rig.tick(0, "off")
    assert rig.commands == []
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [True]
    rig.tick(2300, "on")
    rig.now = start + timedelta(hours=3)
    rig.tick(2300, "on")
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "completed"


def test_cancel_before_start_never_turns_on(tmp_path):
    rig, advice, command, start = prepare(tmp_path)
    rig.manager.action(command)
    rig.manager.action({"action": "cancel", "session_id": advice["session_id"]})
    rig.tick(0, "off")
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == []
    assert rig.manager.view()["sessions"][-1]["state"] == "cancelled"


@pytest.mark.parametrize("mutation", ["expired", "revision", "energy", "past", "cancelled"])
def test_unexecutable_advice_rejected(tmp_path, mutation):
    rig, advice, command, start = prepare(tmp_path)
    if mutation == "expired":
        rig.now += timedelta(seconds=301)
    elif mutation == "revision":
        command["request_revision"] = 2
    elif mutation == "energy":
        advice["slots"][0]["energy_wh"] = 1000
        assert rig.manager.receive_advice(advice)
    elif mutation == "past":
        rig.now = start + timedelta(minutes=2)
        advice["generated_at"] = rig.now.isoformat()
        command["generated_at"] = advice["generated_at"]
        assert rig.manager.receive_advice(advice)
    else:
        rig.manager.action({"action": "cancel_advice"})
    with pytest.raises(ValueError):
        rig.manager.action(command)
    assert rig.manager.view()["sessions"] == []


def test_early_on_is_switched_off_without_finishing_session(tmp_path):
    rig, _, command, _ = prepare(tmp_path)
    rig.manager.action(command)
    rig.tick(0, "on")
    assert rig.commands == [False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "planned"


def test_manual_off_during_charging_is_respected(tmp_path):
    rig, _, command, start = prepare(tmp_path)
    rig.manager.action(command)
    rig.now = start
    rig.tick(0, "off")
    rig.tick(2300, "on")
    rig.tick(0, "off", seconds=20)
    assert rig.commands == [True]
    assert rig.manager.view()["sessions"][-1]["manual_pause"] is True


def test_restart_after_window_never_starts_and_retains_shortfall(tmp_path):
    rig, _, command, start = prepare(tmp_path)
    rig.manager.action(command)
    rig.now = start + timedelta(hours=4)
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.tick(0, "off")
    session = rig.manager.view()["sessions"][-1]
    assert rig.commands == []
    assert session["state"] == "completed"
    assert session["remaining_energy_wh"] == 6900


def test_unknown_switch_does_not_start(tmp_path):
    rig, _, command, start = prepare(tmp_path)
    rig.manager.action(command)
    rig.now = start
    rig.tick(None, "unavailable")
    assert rig.commands == []
