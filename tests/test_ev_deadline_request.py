from datetime import timedelta

import pytest
from test_ev_direct_start import profile
from test_ev_sessions import POWER, SWITCH, Rig

from picot_energy_devices.ev_sessions import EVSessionManager


def request(rig):
    profile(rig)
    rig.manager.action({"action": "request_advice",
                        "ready_by": (rig.now + timedelta(days=2)).isoformat(),
                        "required_energy_wh": 6900})
    return rig.manager.view()["charging_request"]


def test_advice_request_is_durable_and_never_switches(tmp_path):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    assert demand["remaining_energy_wh"] == 6900
    assert demand["evidence_source"] == "user_grid_energy_estimate"
    rig.manager = EVSessionManager(tmp_path / "ev", power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    assert rig.manager.view()["charging_request"] == demand
    rig.tick(0, "off")
    assert rig.commands == []
    assert rig.manager.snapshot()["session"] is None


def test_cancel_and_revision_reject_old_advice(tmp_path):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    advice = {"contract": "energy-device-charging-advice:v1",
              "session_id": demand["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(), "status": "provisional"}
    assert rig.manager.receive_advice(advice)
    rig.manager.action({"action": "request_advice", "ready_by": demand["ready_by"],
                        "required_energy_wh": 4600})
    assert not rig.manager.receive_advice(advice)
    rig.manager.action({"action": "cancel_advice"})
    assert rig.manager.view()["charging_advice"] is None
    assert not rig.manager.receive_advice(dict(advice, request_revision=2))


def test_duplicate_request_keeps_identity_revision_and_evidence_time(tmp_path):
    rig = Rig(tmp_path / "ev")
    original = request(rig)
    rig.now += timedelta(seconds=10)
    rig.manager.action({"action": "request_advice", "ready_by": original["ready_by"],
                        "required_energy_wh": original["remaining_energy_wh"]})
    assert rig.manager.view()["charging_request"] == original


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), 90000])
def test_invalid_demand(tmp_path, value):
    rig = Rig(tmp_path / "ev")
    profile(rig)
    with pytest.raises(ValueError):
        rig.manager.action({"action": "request_advice", "required_energy_wh": value,
                            "ready_by": (rig.now + timedelta(days=2)).isoformat()})


def test_direct_start_supersedes_request_without_double_demand(tmp_path):
    rig = Rig(tmp_path / "ev")
    request(rig)
    rig.manager.action({"action": "start_now"})
    assert rig.manager.advice_exchange()["request"]["state"] == "cancelled"
    assert rig.manager.snapshot()["session"]["remaining_energy_wh"] == 9200


def test_expired_and_future_advice_rejected(tmp_path):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    for seconds in (-301, 1):
        assert not rig.manager.receive_advice({
            **demand, "contract": "energy-device-charging-advice:v1",
            "status": "provisional",
            "generated_at": (rig.now + timedelta(seconds=seconds)).isoformat(),
        })


@pytest.mark.parametrize("changes", [{"slots": {}}, {"slots": ["bad"]},
                                      {"status": "execute"}, {"request_revision": True}])
def test_malformed_advice_cannot_break_dashboard_state(tmp_path, changes):
    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    advice = {**demand, "contract": "energy-device-charging-advice:v1",
              "status": "ready", "generated_at": rig.now.isoformat(), **changes}
    assert not rig.manager.receive_advice(advice)
    assert rig.manager.view()["charging_advice"] is None


def test_exchange_transports_request_and_advice_without_switch_capability(tmp_path):
    from picot_energy_devices.charging_advice import exchange_once

    rig = Rig(tmp_path / "ev")
    demand = request(rig)
    sent = []

    class HA:
        def publish_catalog(self, entity, envelope):
            sent.append((entity, envelope))

        def state(self, entity):
            assert entity == "sensor.picot_ev_charging_advice"
            return {"attributes": {"contract": "energy-device-charging-advice:v1",
                                   "session_id": demand["session_id"],
                                   "request_revision": demand["request_revision"],
                                   "generated_at": rig.now.isoformat(), "status": "blocked"}}

    exchange_once(rig.manager, HA())
    assert sent[0][0] == "sensor.picot_ev_charging_request"
    assert sent[0][1]["request"] == demand
    assert rig.manager.view()["charging_advice"]["status"] == "blocked"
    assert rig.commands == []


def test_real_http_handler_accepts_deadline_without_creating_execution(tmp_path):
    import json

    from test_ev_direct_start_http import Connection

    from picot_energy_devices.store import EnergyDeviceStore
    from picot_energy_devices.web_ui import create_web_server

    rig = Rig(tmp_path / "ev")
    profile(rig)
    server = create_web_server(EnergyDeviceStore(tmp_path / "registry"),
                               host="127.0.0.1", port=0, ev_sessions=rig.manager)
    try:
        connection = Connection({"action": "request_advice", "required_energy_wh": 4600,
                                 "ready_by": (rig.now + timedelta(days=2)).isoformat()})
        server.RequestHandlerClass(connection, ("127.0.0.1", 0), server)
        header, body = bytes(connection.response).split(b"\r\n\r\n", 1)
        assert b"200 OK" in header
        assert json.loads(body)["charging_request"]["remaining_energy_wh"] == 4600
        rig.tick(None, "off")
        assert rig.commands == []
    finally:
        server.server_close()
