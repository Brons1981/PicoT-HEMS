from datetime import timedelta

import pytest
from test_ev_direct_start import profile
from test_ev_sessions import POWER, SWITCH, Rig

from picot_energy_devices.charging_advice import exchange_once
from picot_energy_devices.ev_sessions import EVSessionManager


def test_fixed_start_without_recognition_or_cable(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    start = rig.now + timedelta(hours=1)
    rig.manager.action({"action": "start_at", "planned_start": start.isoformat()})
    rig.tick(0, "off")
    assert rig.commands == []
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [True]


def test_plug_creates_one_durable_automatic_request(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "save_auto_charge", "enabled": True,
                        "ready_time": "07:00", "timezone": "Europe/Amsterdam"})
    stamp = rig.now.isoformat()
    rig.manager.observe_plug("on", stamp)
    first = rig.manager.view()["charging_request"]
    assert first["automatic_execution"] is True
    assert first["ready_by"] == "2026-10-11T05:00:00+00:00"
    rig.manager.observe_plug("unavailable", None)
    rig.manager.observe_plug("on", stamp)
    assert rig.manager.view()["charging_request"] == first
    rig.now += timedelta(seconds=1)
    rig.manager.observe_plug("off", rig.now.isoformat())
    assert rig.manager.view()["charging_request"]["state"] == "cancelled"


def test_automatic_advice_accepts_without_second_click(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "request_automatic",
                        "ready_by": (rig.now + timedelta(days=1)).isoformat(),
                        "required_energy_wh": 6900})
    demand = rig.manager.view()["charging_request"]
    start = rig.now + timedelta(hours=1)
    advice = {"contract": "energy-device-charging-advice:v1", "status": "ready",
              "session_id": demand["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(), "selection_id": "choice-1",
              "slots": [{"starts_at": start.isoformat(),
                         "ends_at": (start + timedelta(hours=3)).isoformat(),
                         "energy_wh": 6900}]}
    assert rig.manager.receive_advice(advice)
    session = rig.manager.view()["sessions"][-1]
    assert session["joint_pending"]
    assert not session["confirmed"]
    rig.tick(0, "off")
    assert not rig.commands
    assert rig.manager.receive_advice(advice | {"execution_status": "blocked",
        "reason": "joint_selection_expired_request_new_advice"})
    demand2 = rig.manager.view()["charging_request"]
    assert demand2["state"] == "requested"
    assert demand2["request_revision"] == 2
    assert not rig.manager.receive_advice(advice)
    assert rig.manager.current(rig.manager.view()) is None


def target(rig):
    profile(rig)
    rig.manager.action({"action": "save_charge_target", "enabled": True,
                        "percent": 80, "full_charge_kwh": 11.7})
    rig.manager.observe_soc("30", rig.now.isoformat())


def test_soc_estimate_and_target_stop(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "start_now"})
    session = rig.manager.view()["sessions"][-1]
    assert session["target_energy_wh"] == 5850
    assert session["expected_duration_seconds"] == pytest.approx(5850 / 2300 * 3600)
    rig.tick(0, "off")
    rig.tick(2300, "on")
    rig.manager.observe_soc("80", rig.now.isoformat())
    rig.tick(2300, "on")
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["completion_reason"] == "soc_target_reached"


def test_soc_target_drives_automatic_request(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "request_automatic",
                        "ready_by": (rig.now + timedelta(days=1)).isoformat(),
                        "required_energy_wh": 6900})
    assert rig.manager.view()["charging_request"]["remaining_energy_wh"] == 5850


@pytest.mark.parametrize("soc", [None, "unavailable", "NaN", "101", "-1"])
def test_invalid_soc_never_creates_target_session(tmp_path, soc):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.observe_soc(soc, rig.now.isoformat())
    with pytest.raises(ValueError, match="actueel SOC"):
        rig.manager.action({"action": "start_now"})
    assert not rig.manager.view()["sessions"]


def test_target_already_reached_does_not_charge(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.observe_soc("85", rig.now.isoformat())
    with pytest.raises(ValueError, match="Laaddoel bereikt"):
        rig.manager.action({"action": "start_now"})


def test_stale_soc_waits_without_consuming_connection(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "save_auto_charge", "enabled": True})
    rig.now += timedelta(minutes=31)
    stamp = rig.now.isoformat()
    rig.manager.observe_plug("on", stamp)
    assert not rig.manager.view().get("charging_request")
    rig.manager.observe_soc("40", rig.now.isoformat())
    rig.manager.observe_plug("on", stamp)
    assert rig.manager.view()["charging_request"]["remaining_energy_wh"] == 4680


def test_connection_survives_restart_and_cancel(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "save_auto_charge", "enabled": True})
    stamp = rig.now.isoformat()
    rig.manager.observe_plug("on", stamp)
    demand = rig.manager.view()["charging_request"]
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.manager.observe_plug("on", stamp)
    assert rig.manager.view()["charging_request"] == demand
    rig.manager.action({"action": "cancel_advice"})
    rig.manager.observe_plug("on", stamp)
    assert rig.manager.view()["charging_request"]["state"] == "cancelled"
    rig.now += timedelta(seconds=1)
    rig.manager.observe_plug("off", rig.now.isoformat())
    rig.now += timedelta(seconds=1)
    rig.manager.observe_plug("on", rig.now.isoformat())
    assert rig.manager.view()["charging_request"]["session_id"] != demand["session_id"]


def test_fixed_schedule_survives_restart_and_ignores_plug_off(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    start = rig.now + timedelta(hours=1)
    rig.manager.action({"action": "start_at", "planned_start": start.isoformat()})
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.manager.observe_plug("off", rig.now.isoformat())
    rig.tick(0, "on")
    assert rig.commands == [False]
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [False, True]


def test_automatic_pending_holds_plug_off_without_recognizing_charge(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "request_automatic",
                        "ready_by": (rig.now + timedelta(days=1)).isoformat(),
                        "required_energy_wh": 6900})
    rig.tick(2300, "on")
    assert rig.commands == [False]
    assert rig.manager.current(rig.manager.view()) is None
    rig.now += timedelta(minutes=6)
    rig.manager.refresh_automatic_request()
    assert rig.manager.view()["charging_request"]["request_revision"] == 2


def test_plug_to_advice_receipt_restart_start_disconnect(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "save_auto_charge", "enabled": True})
    stamp = rig.now.isoformat()
    rig.manager.observe_plug("on", stamp)
    request = rig.manager.view()["charging_request"]
    start = rig.now + timedelta(hours=1)
    energy = request["remaining_energy_wh"]
    duration = energy / request["fixed_power_w"] * 3600
    advice = {"contract": "energy-device-charging-advice:v1", "status": "ready",
              "session_id": request["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(), "selection_id": "joint-choice",
              "slots": [{"starts_at": start.isoformat(),
                         "ends_at": (start + timedelta(seconds=duration)).isoformat(),
                         "energy_wh": energy}]}

    class HA:
        def __init__(self):
            self.requests = []

        def publish_catalog(self, entity, envelope):
            self.requests.append(envelope)

        def state(self, entity):
            return {"attributes": advice}

    client = HA()
    exchange_once(rig.manager, client)
    assert [p["request"]["state"] for p in client.requests] == ["requested", "accepted"]
    assert rig.manager.receive_advice(advice | {
        "execution_status": "committed", "committed_at": rig.now.isoformat(),
        "battery_plan_id": "battery-plan"})
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.now = start
    rig.manager.observe_plug("unavailable", None)
    rig.tick(0, "off")
    assert rig.commands == []
    rig.manager.observe_plug("on", stamp)
    rig.tick(0, "off")
    assert rig.commands == [True]
    rig.tick(2300, "on")
    rig.manager.observe_plug("off", rig.now.isoformat())
    rig.tick(2300, "on")
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "cancelled"


def test_deadline_expiry_never_rolls_into_next_day(tmp_path):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    rig.manager.action({"action": "save_auto_charge", "enabled": True})
    stamp = rig.now.isoformat()
    rig.manager.observe_plug("on", stamp)
    rig.now += timedelta(days=1)
    rig.manager.refresh_automatic_request()
    rig.manager.observe_plug("on", stamp)
    assert rig.manager.view()["charging_request"]["state"] == "expired"


def test_fixed_start_http_without_cable_recognition(tmp_path):
    import json

    from test_ev_direct_start_http import Connection

    from picot_energy_devices.store import EnergyDeviceStore
    from picot_energy_devices.web_ui import create_web_server

    rig = Rig(tmp_path / "ev")
    profile(rig)
    server = create_web_server(EnergyDeviceStore(tmp_path / "registry"),
                               host="127.0.0.1", port=0, ev_sessions=rig.manager)
    try:
        connection = Connection({"action": "start_at",
                                 "planned_start": (rig.now + timedelta(hours=1)).isoformat()})
        server.RequestHandlerClass(connection, ("127.0.0.1", 0), server)
        header, body = bytes(connection.response).split(b"\r\n\r\n", 1)
        assert b"200 OK" in header
        assert json.loads(body)["sessions"][-1]["fixed_start"]
    finally:
        server.server_close()


def test_one_time_full_keeps_normal_target_and_survives_restart(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "request_full_charge"})
    request = rig.manager.view()["charging_request"]
    assert request["soc_target"] == 100
    assert request["remaining_energy_wh"] == pytest.approx(8190)
    assert request["automatic_execution"]
    assert rig.manager.view()["charge_target"]["percent"] == 80
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    assert rig.manager.view()["charging_request"] == request
    rig.manager.action({"action": "cancel_advice"})
    rig.manager.action({"action": "start_now"})
    assert rig.manager.view()["sessions"][-1]["soc_target"] == 80
    assert rig.manager.view()["sessions"][-1]["target_energy_wh"] == pytest.approx(5850)


def test_one_time_full_requires_fresh_soc(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.now += timedelta(minutes=31)
    with pytest.raises(ValueError, match="actueel SOC"):
        rig.manager.action({"action": "request_full_charge"})
    assert not rig.manager.view().get("charging_request")


def test_full_charge_advice_executes_to_100_not_80(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "request_full_charge"})
    request = rig.manager.view()["charging_request"]
    start = rig.now + timedelta(minutes=1)
    advice = {"contract": "energy-device-charging-advice:v1", "status": "ready",
              "session_id": request["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(),
              "slots": [{"starts_at": start.isoformat(),
                         "ends_at": (start + timedelta(seconds=8190/2300*3600)).isoformat(),
                         "energy_wh": 8190}]}
    assert rig.manager.receive_advice(advice)
    assert rig.manager.view()["sessions"][-1]["soc_target"] == 100
    rig.now = start
    rig.tick(0, "off")
    rig.manager.observe_soc("80", rig.now.isoformat())
    rig.tick(2300, "on")
    assert rig.commands == [True]
    rig.manager.observe_soc("100", rig.now.isoformat())
    rig.tick(2300, "on")
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    rig.manager.observe_soc("40", rig.now.isoformat())
    rig.manager.action({"action": "start_now"})
    assert rig.manager.view()["sessions"][-1]["soc_target"] == 80


def test_full_charge_does_not_change_running_session(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.action({"action": "start_now"})
    before = rig.manager.view()
    with pytest.raises(ValueError, match="bestaande laadsessie"):
        rig.manager.action({"action": "request_full_charge"})
    assert rig.manager.view() == before


def test_soc_rejection_retains_value_and_explains_age(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    stamp = (rig.now - timedelta(hours=2)).isoformat()
    rig.manager.observe_soc("38", stamp)
    observation = rig.manager.view()["soc_observation"]
    assert observation["status"] == "stale"
    assert observation["raw_state"] == "38"
    assert observation["age_seconds"] == 7200
    assert rig.manager.view()["vehicle_soc"] is None
    with pytest.raises(ValueError, match="120 minuten oud"):
        rig.manager.action({"action": "start_now"})
    rig.manager.observe_soc("38", rig.now.isoformat())
    assert rig.manager.view()["soc_observation"]["status"] == "ready"
    assert rig.manager.view()["vehicle_soc"]["percent"] == 38


@pytest.mark.parametrize("value,stamp,error,status", [
    ("unavailable", None, None, "unavailable"),
    ("38", None, None, "missing_timestamp"),
    (None, None, "read_failed", "read_failed"),
])
def test_soc_failure_reasons_are_distinct(tmp_path, value, stamp, error, status):
    rig = Rig(tmp_path / "ev")
    rig.manager.observe_soc(value, stamp, error=error)
    assert rig.manager.view()["soc_observation"]["status"] == status


def test_unchanged_soc_after_connection_plans_eight_percent(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    connected = (rig.now - timedelta(hours=4)).isoformat()
    reported = (rig.now - timedelta(hours=2)).isoformat()
    rig.manager.observe_plug("on", connected)
    rig.manager.observe_soc("72.0", reported)
    assert rig.manager.view()["vehicle_soc"]["percent"] == 72
    rig.manager.action({"action": "save_auto_charge", "enabled": True})
    rig.manager.observe_plug("on", connected)
    request = rig.manager.view()["charging_request"]
    assert request["remaining_energy_wh"] == pytest.approx(936)


def test_old_soc_cannot_cross_reconnection_or_missing_plug(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    reported = (rig.now - timedelta(hours=2)).isoformat()
    rig.manager.observe_plug("on", (rig.now - timedelta(hours=4)).isoformat())
    rig.manager.observe_soc("72", reported)
    assert rig.manager.view()["vehicle_soc"]
    rig.manager.observe_plug("off", rig.now.isoformat())
    rig.now += timedelta(seconds=1)
    rig.manager.observe_plug("on", rig.now.isoformat())
    rig.manager.observe_soc("72", reported)
    assert rig.manager.view()["vehicle_soc"] is None
    with pytest.raises(ValueError, match="actueel SOC"):
        rig.manager.action({"action": "start_now"})


def test_connection_soc_rechecked_at_action_and_after_charging(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    connected = (rig.now - timedelta(hours=4)).isoformat()
    reported = (rig.now - timedelta(hours=2)).isoformat()
    rig.manager.observe_plug("on", connected)
    rig.manager.observe_soc("72", reported)
    rig.now += timedelta(seconds=31)
    with pytest.raises(ValueError, match="actueel SOC"):
        rig.manager.action({"action": "start_now"})
    rig.manager.observe_plug("on", connected)
    rig.tick(2300, "on")
    rig.manager.observe_soc("72", reported)
    assert rig.manager.view()["vehicle_soc"] is None


def test_recent_report_from_before_connection_is_not_starting_soc(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    rig.manager.observe_plug("on", rig.now.isoformat())
    rig.manager.observe_soc("72", (rig.now-timedelta(minutes=1)).isoformat())
    assert rig.manager.view()["vehicle_soc"] is None


def test_same_connection_soc_survives_restart_with_fresh_plug_check(tmp_path):
    rig = Rig(tmp_path / "ev")
    target(rig)
    connected = (rig.now-timedelta(hours=4)).isoformat()
    reported = (rig.now-timedelta(hours=2)).isoformat()
    rig.manager.observe_plug("on", connected)
    rig.manager.observe_soc("72", reported)
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    rig.manager.observe_plug("on", connected)
    rig.manager.action({"action": "start_now"})
    assert rig.manager.view()["sessions"][-1]["target_energy_wh"] == pytest.approx(936)
