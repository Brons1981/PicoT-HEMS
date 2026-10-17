from datetime import timedelta

import pytest
from test_ev_sessions import POWER, SWITCH, Rig

from picot.v2.external_load_policy import read_session_demand
from picot_energy_devices.ev_sessions import EVSessionManager


def profile(rig):
    rig.manager.action({"action": "save_profile", "expected_power_w": 2300,
                        "expected_duration_seconds": 14400})


def test_button_creates_demand_without_recognition_and_starts_selected_plug(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    session = rig.manager.view()["sessions"][-1]
    assert session["confirmed"]
    assert session["remaining_energy_wh"] == 9200
    assert session["last_measured_at"] is None
    assert session["current_power_w"] is None
    rig.tick(0, "off")
    assert rig.commands == [True]
    demand = read_session_demand(rig.manager.snapshot(), captured_at=rig.now,
                                 execution_scope_id="home")
    assert demand is not None
    assert demand.remaining_energy_wh == 9200
    assert demand.power_w == 0
    rig.tick(2300, "on")
    assert rig.manager.view()["sessions"][-1]["state"] == "active"


def test_profile_and_start_intent_survive_restart_and_duplicate_click(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    session = rig.manager.view()["sessions"][-1]
    with pytest.raises(ValueError, match="sessie"):
        rig.manager.action({"action": "start_now"})
    rig.manager = EVSessionManager(tmp_path / "ev", power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    assert rig.manager.view()["profile"]["expected_power_w"] == 2300
    rig.tick(None, "off")
    assert rig.commands == [True]
    assert rig.manager.view()["sessions"][-1]["session_id"] == session["session_id"]
    assert rig.manager.view()["sessions"][-1]["delivered_energy_wh"] == 0


def test_no_charging_is_reported_not_completed_and_manual_off_is_respected(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    rig.tick(0, "off")
    rig.tick(0, "on")
    rig.tick(0, "on", seconds=121)
    session = rig.manager.view()["sessions"][-1]
    assert session["start_status"] == "charging_not_started"
    assert session["state"] != "completed"
    rig.tick(0, "off", seconds=10)
    assert rig.commands == [True]
    assert rig.manager.view()["sessions"][-1]["manual_pause"]
    rig.manager.action({"action": "resume"})
    rig.tick(0, "off")
    assert rig.commands == [True, True]
    rig.tick(2300, "on")
    assert rig.manager.view()["sessions"][-1]["start_status"] == "charging"


def test_direct_start_service_failure_retries_after_restart(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})

    def fail(_enabled):
        raise OSError("service unavailable")

    rig.manager.tick(measured_at=None, power_w=None, switch_state="off", set_switch=fail)
    assert rig.manager.view()["sessions"][-1]["error"] == "service unavailable"
    rig.manager = EVSessionManager(tmp_path / "ev", power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.tick(None, "off", seconds=5)
    assert not rig.commands
    rig.tick(None, "off", seconds=5)
    assert rig.commands == [True]


def test_profile_edit_does_not_change_active_session_and_missing_data_is_not_full(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    rig.manager.action({"action": "save_profile", "expected_power_w": 2000,
                        "expected_duration_seconds": 3600})
    rig.tick(None, "off")
    rig.tick(None, "on", seconds=400)
    session = rig.manager.view()["sessions"][-1]
    assert session["expected_power_w"] == 2300
    assert session["remaining_energy_wh"] == 9200
    assert session["state"] != "completed"
    assert session["start_status"] == "measurement_unavailable"


def test_cancel_before_first_tick_and_expired_restart_never_start(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    sid = rig.manager.view()["sessions"][-1]["session_id"]
    rig.manager.action({"action": "cancel", "session_id": sid})
    rig.tick(None, "off")
    assert not rig.commands
    rig.manager.action({"action": "start_now"})
    rig.now += timedelta(hours=5)
    rig.tick(None, "off")
    assert not rig.commands
    assert rig.manager.view()["sessions"][-1]["completion_reason"] == "scheduled_deadline"


@pytest.mark.parametrize("power,duration", [(0, 3600), (2300, 0), (float("nan"), 3600),
                                            (2300, float("inf")), (True, 3600)])
def test_invalid_profile_never_creates_session(tmp_path, power, duration):
    rig = Rig(tmp_path / "ev")
    with pytest.raises(ValueError):
        rig.manager.action({"action": "save_profile", "expected_power_w": power,
                            "expected_duration_seconds": duration})
    assert not rig.manager.view()["sessions"]


def test_start_requires_saved_profile_and_unknown_switch_does_not_dispatch(tmp_path):
    rig = Rig(tmp_path / "ev")
    with pytest.raises(ValueError, match="profiel"):
        rig.manager.action({"action": "start_now"})
    profile(rig)
    rig.manager.action({"action": "start_now"})
    rig.tick(None, "unavailable")
    assert not rig.commands


def test_pre_session_measurement_cannot_confirm_charging(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    rig.manager.tick(measured_at=rig.now - timedelta(seconds=2), power_w=2300,
                     switch_state="on", set_switch=rig.commands.append)
    session = rig.manager.view()["sessions"][-1]
    assert session["current_power_w"] is None
    assert not session.get("charging_observed")
    assert session["delivered_energy_wh"] == 0


def test_direct_charge_natural_end_stops_after_measured_charging(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "start_now"})
    rig.tick(0, "off")
    rig.tick(2300, "on")
    for _ in range(301):
        rig.tick(0, "on")
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["completion_reason"] == "measured_low_power"
