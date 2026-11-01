from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import request, scenario

from picot.v2.ev_deadline_advice import _overlay
from picot.v2.ev_joint_adoption import JointEVAdopter
from picot.v2.ev_joint_selection import JointEVSelection
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def setup(tmp_path):
    store, snapshot, plan = scenario(tmp_path, soc=0.9)
    start = snapshot.captured_at + timedelta(hours=14)
    end = start + timedelta(minutes=30)
    selected = JointEVSelection(
        snapshot=_overlay(snapshot, start, end, 2000, plan.valid_until),
        request=request(snapshot), retained_plan_id=plan.plan_id, plan=plan,
        starts_at=start, ends_at=end, selection_id="test-joint-ev",
    )
    adopter = JointEVAdopter(store, lambda _: inputs()["conversion_model"])
    return store, snapshot, selected, adopter


def test_acceptance_records_exact_plan_and_survives_restart(tmp_path):
    store, snapshot, selected, adopter = setup(tmp_path)
    receipt = adopter.adopt(selected, snapshot)
    assert receipt["battery_plan_id"] == selected.plan.plan_id
    assert receipt["session_id"] == selected.request["session_id"]
    assert receipt["execution_status"] == "committed"
    before = store._load_payload()
    assert adopter.adopt(selected, snapshot) == receipt
    assert store._load_payload() == before
    restarted = JointEVAdopter(ActivePlanCommitmentStore(store._path),
                               lambda _: inputs()["conversion_model"])
    assert restarted.receipt(selected.selection_id) == receipt


def test_expired_advice_cannot_change_commitments(tmp_path):
    store, snapshot, selected, adopter = setup(tmp_path)
    before = store._load_payload()
    later = snapshot.captured_at + timedelta(minutes=5)
    with pytest.raises(ValueError, match="expired"):
        adopter.adopt(selected, replace(snapshot, captured_at=later,
            daily_charge_context=None, capability_snapshot_set=None,
            storage_mode_capability_evidence=None))
    assert store._load_payload() == before


def test_disabled_execution_does_not_acknowledge_ev(tmp_path):
    store, snapshot, selected, _ = setup(tmp_path)
    adopter = JointEVAdopter(store, lambda _: inputs()["conversion_model"], execution_enabled=False)
    before = store._load_payload()
    with pytest.raises(ValueError, match="execution_disabled"):
        adopter.adopt(selected, snapshot)
    assert store._load_payload() == before
    assert adopter.receipt(selected.selection_id) is None


def test_changed_owner_cannot_adopt_or_replay_a_receipt(tmp_path):
    store, snapshot, selected, adopter = setup(tmp_path)
    with pytest.raises(ValueError, match="owner_changed"):
        adopter.adopt(replace(selected, retained_plan_id="obsolete"), snapshot)
    assert store.load_joint_ev_receipt(selected.selection_id) is None


def test_fresh_soc_shortfall_rejects_old_physical_proof(tmp_path):
    store, snapshot, selected, adopter = setup(tmp_path)
    changed = replace(snapshot, current_storage_states=tuple(
        replace(s, current_soc=0.1) for s in snapshot.current_storage_states))
    before = store._load_payload()
    with pytest.raises(ValueError, match="fresh_validation_failed"):
        adopter.adopt(selected, changed)
    assert store._load_payload() == before


def test_common_terminal_reserve_is_rechecked_at_acceptance(tmp_path):
    store, snapshot, selected, adopter = setup(tmp_path)
    before = store._load_payload()
    selected = replace(selected, terminal_storage_requirement_wh=100000)
    with pytest.raises(ValueError, match="terminal_reserve_changed"):
        adopter.adopt(selected, snapshot)
    assert store._load_payload() == before


def test_main_loop_recaptures_after_joint_publication():
    from test_v2_live_replan_poll_cycle import BASE, _bundle

    from picot.v2.live_runtime import _poll_live_cycle

    old = _bundle(captured_at=BASE, price=0.2)
    fresh = _bundle(captured_at=BASE + timedelta(seconds=1), price=0.2)
    bundles = iter((old, fresh))
    executed = []
    _poll_live_cycle(previous_signature=None, load_bundle=lambda: next(bundles),
                     observe=lambda _: True, execute=lambda b: executed.append(b))
    assert executed == [fresh]


def revised_setup(tmp_path):
    from picot.v2.ev_joint_selection import rebuilt_selection

    store, snapshot, selected, adopter = setup(tmp_path)
    revised = rebuilt_selection(selected.snapshot, selected.request, selected.plan,
                                inputs()["conversion_model"], 0)
    assert revised is not None
    revised = replace(revised, selection_id=selected.selection_id,
                      starts_at=selected.starts_at, ends_at=selected.ends_at,
                      trigger=replace(revised.trigger, request=replace(
                          revised.trigger.request, request_id="joint-ev:" + selected.selection_id)))
    return store, snapshot, revised, adopter


def test_revised_route_and_receipt_are_published_together(tmp_path):
    store, snapshot, selected, adopter = revised_setup(tmp_path)
    previous = store.load_daily_assignments()[0]
    receipt = adopter.adopt(selected, snapshot)
    assert receipt["battery_plan_id"] == selected.plan.plan_id
    assert store.load_active_daily_main_plan(selected.plan.execution_scope_id) == selected.plan
    revised = next(a for a in store.load_daily_assignments()
                   if a.assignment_id == selected.window.assignment_id)
    assert revised.revision == previous.revision + 1
    assert revised.completed_at is None
    assert store.load_daily_recalculation_request() is None
    assert store.daily_recalculation_status()["status"] == "completed"
    assert adopter.adopt(selected, snapshot) == receipt


def test_failed_revision_does_not_leave_pending_recalculation(tmp_path, monkeypatch):
    store, snapshot, selected, adopter = revised_setup(tmp_path)
    before = store._load_payload()

    def fail(*args, **kwargs):
        raise ValueError("injected publication validation failure")

    monkeypatch.setattr(store, "_bind_supplemental", fail)
    with pytest.raises(ValueError, match="injected publication"):
        adopter.adopt(selected, snapshot)
    assert store._load_payload() == before
    assert store.load_joint_ev_receipt(selected.selection_id) is None


def test_joint_acceptance_cannot_replace_an_existing_manual_request(tmp_path):
    store, snapshot, selected, adopter = revised_setup(tmp_path)
    store.request_daily_recalculation(request_id="manual", requested_at=snapshot.captured_at)
    before = store._load_payload()
    with pytest.raises(ValueError, match="scoped revision"):
        adopter.adopt(selected, snapshot)
    assert store._load_payload() == before


def accepted_demand(snapshot, selected):
    from picot.v2.external_load_policy import SESSION_METHOD, read_session_demand

    payload = {"contract": SESSION_METHOD, "source_id": "energy-devices:ev-session",
               "generated_at": snapshot.captured_at.isoformat(), "session": {
        "session_id": selected.request["session_id"], "version": 1, "state": "planned",
        "confirmed": False, "joint_pending": True, "start_status": "waiting_for_hems",
        "recognition_source": "accepted_hems_advice",
        "accepted_advice": {"selection_id": selected.selection_id},
        "planned_start": selected.starts_at.isoformat(), "remaining_energy_wh": 1000,
        "expected_power_w": 2000, "expected_duration_seconds": 1800, "switch_state": "off",
    }}
    policy = read_session_demand(payload, captured_at=snapshot.captured_at,
                                 execution_scope_id=selected.plan.execution_scope_id)
    return payload, policy


def test_accepted_pending_session_is_forecast_once_before_switch_permission(tmp_path):
    from picot.v2.external_load_policy import apply_external_load_policy

    store, snapshot, selected, _ = setup(tmp_path)
    payload, policy = accepted_demand(snapshot, selected)
    assert policy is not None
    assert payload["session"]["confirmed"] is False
    original_wh = sum(i.expected_energy_wh for i in snapshot.household_load_forecast.intervals)
    snapshot = replace(snapshot, external_load_policy=policy, household_load_forecast=(
        apply_external_load_policy(snapshot.household_load_forecast, policy,
                                   captured_at=snapshot.captured_at)))
    assessed = []

    def conversion(changed):
        assessed.append(sum(i.expected_energy_wh
                            for i in changed.household_load_forecast.intervals))
        return inputs()["conversion_model"]

    JointEVAdopter(store, conversion).adopt(selected, snapshot)
    assert assessed == pytest.approx([original_wh + 1000])


def test_unconfirmed_nonaccepted_session_is_not_forecast(tmp_path):
    from picot.v2.external_load_policy import read_session_demand

    _, snapshot, selected, _ = setup(tmp_path)
    payload, _ = accepted_demand(snapshot, selected)
    payload["session"].pop("accepted_advice")
    assert read_session_demand(payload, captured_at=snapshot.captured_at,
                               execution_scope_id=selected.plan.execution_scope_id) is None


def test_pending_forecast_survives_charger_status_feedback(tmp_path):
    from picot.v2.external_load_policy import read_session_demand

    _, snapshot, selected, _ = setup(tmp_path)
    payload, _ = accepted_demand(snapshot, selected)
    payload["session"]["start_status"] = "waiting_for_charging"
    policy = read_session_demand(payload, captured_at=snapshot.captured_at,
                                 execution_scope_id=selected.plan.execution_scope_id)
    assert policy is not None
    assert policy.remaining_energy_wh == 1000
