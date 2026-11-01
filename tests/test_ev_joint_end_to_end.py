"""Real advisor, canonical planner, durable Store and ED execution handshake."""

from dataclasses import replace
from datetime import datetime, timedelta

from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import scenario
from test_ev_direct_start import profile
from test_ev_sessions import POWER, SWITCH, Rig

from picot.v2.ev_deadline_runtime import EVDeadlineAdvisor
from picot.v2.ev_joint_adoption import JointEVAdopter
from picot.v2.external_load_policy import apply_external_load_policy, read_session_demand
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot_energy_devices.ev_sessions import EVSessionManager


def test_real_joint_route_is_adopted_before_ev_starts_and_survives_restart(tmp_path):
    store, snapshot, original = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at
    snapshot = replace(snapshot, price_points=tuple(replace(
        point, value_eur_per_kwh=0.01
        if at + timedelta(hours=22) <= point.starts_at < at + timedelta(hours=26) else 0.8,
    ) for point in snapshot.price_points))
    rig = Rig(tmp_path / "ed")
    rig.now = at
    profile(rig)
    rig.manager.action({"action": "request_advice", "required_energy_wh": 1150,
                        "ready_by": (at + timedelta(minutes=32)).isoformat()})
    conversion = inputs()["conversion_model"]
    adopter = JointEVAdopter(store, lambda _: conversion)
    advisor = EVDeadlineAdvisor(read=rig.manager.advice_exchange,
                                publish=rig.manager.receive_advice,
                                configuration=lambda _: conversion, now=lambda: rig.now,
                                adopt=adopter.adopt, receipt=adopter.receipt)
    before = store._load_payload()
    advisor.refresh(snapshot)
    advice = rig.manager.view()["charging_advice"]
    assert advice["status"] == "ready", advice
    assert advice["battery_route_changed"], advice
    assert advice["savings_eur"] > 0
    assert store._load_payload() == before
    assert rig.commands == []
    rig.manager.action({"action": "execute_advice", "session_id": advice["session_id"],
                        "request_revision": advice["request_revision"],
                        "generated_at": advice["generated_at"]})
    rig.tick(0, "off", seconds=0)
    assert rig.commands == []
    assert rig.manager.snapshot()["session"]["confirmed"] is False
    policy = read_session_demand(rig.manager.snapshot(), captured_at=at,
                                 execution_scope_id=original.execution_scope_id)
    assert policy is not None and policy.remaining_energy_wh == 1150
    forecast = apply_external_load_policy(snapshot.household_load_forecast, policy,
                                           captured_at=at)
    assert abs(sum(i.battery_excluded_energy_wh for i in forecast.intervals) - 1150) < 0.01
    pending_snapshot = replace(snapshot, external_load_policy=policy,
                               household_load_forecast=forecast)
    assert advisor.accept_pending(pending_snapshot)
    receipt = store.load_joint_ev_receipt(advice["selection_id"])
    assert receipt is not None
    assert receipt["battery_plan_id"] != original.plan_id
    assert store.load_active_daily_main_plan(original.execution_scope_id).plan_id == (
        receipt["battery_plan_id"])
    assert rig.manager.snapshot()["session"]["confirmed"] is True
    assert rig.manager.view()["sessions"][-1]["joint_receipt"]["battery_plan_id"] == (
        receipt["battery_plan_id"])
    # Restart both durable owners after ACK; ED keeps exactly the accepted slot.
    rig.manager = EVSessionManager(rig.manager.path, power_entity=POWER,
                                   switch_entity=SWITCH, now=lambda: rig.now)
    restarted = JointEVAdopter(ActivePlanCommitmentStore(store._path), lambda _: conversion)
    assert restarted.receipt(advice["selection_id"]) == receipt
    start = datetime.fromisoformat(advice["slots"][0]["starts_at"])
    end = datetime.fromisoformat(advice["slots"][0]["ends_at"])
    rig.now = start - timedelta(seconds=1)
    rig.tick(0, "off", seconds=0)
    assert rig.commands == []
    rig.now = start
    rig.tick(0, "off", seconds=0)
    assert rig.commands == [True]
    rig.tick(2300, "on")
    rig.now = end
    rig.tick(2300, "on", seconds=0)
    assert rig.commands == [True, False]
    rig.tick(0, "off")
    assert rig.manager.view()["sessions"][-1]["state"] == "completed"
