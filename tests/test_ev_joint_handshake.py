from datetime import timedelta

from test_ev_advice_execution import prepare
from test_ev_sessions import POWER, SWITCH

from picot_energy_devices.ev_sessions import EVSessionManager


def pending(tmp_path):
    rig, advice, command, start = prepare(tmp_path)
    advice["selection_id"] = "joint-selection-1"
    assert rig.manager.receive_advice(advice)
    rig.manager.action(command)
    return rig, advice, start


def receipt(rig, advice):
    return dict(advice, execution_status="committed", battery_plan_id="joint-battery-plan",
                committed_at=rig.now.isoformat())


def test_joint_session_waits_for_durable_hems_confirmation_across_restart(tmp_path):
    rig, advice, start = pending(tmp_path)
    exchange = rig.manager.advice_exchange()
    assert exchange["selected_advice"]["selection_id"] == advice["selection_id"]
    assert rig.manager.snapshot()["session"]["joint_pending"]
    assert not rig.manager.snapshot()["session"]["confirmed"]
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                  switch_entity=SWITCH, now=lambda: rig.now)
    rig.now = start - timedelta(seconds=2)
    rig.tick(0, "off")
    assert rig.commands == []
    assert rig.manager.receive_advice(receipt(rig, advice))
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == [True]
    assert rig.manager.snapshot()["session"]["confirmed"]


def test_wrong_or_cancelled_joint_receipt_cannot_start(tmp_path):
    rig, advice, start = pending(tmp_path)
    assert not rig.manager.receive_advice(dict(receipt(rig, advice), selection_id="other"))
    rig.manager.action({"action": "cancel_advice"})
    assert not rig.manager.receive_advice(receipt(rig, advice))
    rig.now = start
    rig.tick(0, "off")
    assert rig.commands == []


def test_old_confirmation_is_rejected(tmp_path):
    rig, advice, _ = pending(tmp_path)
    ack = receipt(rig, advice)
    rig.now += timedelta(minutes=6)
    assert not rig.manager.receive_advice(ack)


def test_delayed_confirmation_cannot_start_incomplete_energy_window(tmp_path):
    rig, advice, start = pending(tmp_path)
    rig.now = start + timedelta(minutes=1)
    assert not rig.manager.receive_advice(receipt(rig, advice))
    rig.tick(0, "off")
    assert rig.commands == []


def test_session_cancel_withdraws_pending_joint_acceptance(tmp_path):
    rig, advice, _ = pending(tmp_path)
    rig.manager.action({"action": "cancel", "session_id": advice["session_id"]})
    assert rig.manager.advice_exchange()["request"]["state"] == "cancelled"
