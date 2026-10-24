import copy
from dataclasses import replace
from datetime import timedelta

import pytest
from picot.v2.accepted_loads import AcceptedLoads
from picot.v2.live_runtime import _planning_input_signature
from picot.v2.planning_input import PlanningInputBundle
from picot_hc.energy_portfolio import RESPONSE_ENTITY
from test_energy_selection import setup as selection_setup
from test_load_replacement import basis_for


def approved(tmp_path, *, modeled=False):
    retained, snapshot, basis, worker, clock, states, local, _, selector, _ = selection_setup(
        tmp_path
    )
    if modeled:
        basis = replace(basis, modeled_source_id="c" * 64)
        local.pending["modeled_source_id"] = "c" * 64
    slot = local.pending["plans"][0]["slots"][0]
    slot.update(
        starts_at=(clock[0] + timedelta(seconds=30)).isoformat(),
        ends_at=(clock[0] + timedelta(seconds=3630)).isoformat(),
    )
    journal = AcceptedLoads(tmp_path / "accepted.sqlite")
    worker.accepted_loads = journal
    permits = []
    worker.publish_permit = permits.append
    worker.refresh(snapshot, basis)
    assert worker.last_answer["status"] == "selected"
    states[RESPONSE_ENTITY]["attributes"] = worker.last_answer
    selector.tick(states, local, clock[0].timestamp(), True)
    worker.poll_selection()
    assert permits[-1]["state"] == "permitted"
    selected = selector.current["message"]
    receipt = dict(
        contract="hc-energy-execution:v1",
        status="running",
        request_id=selected["request_id"],
        request_fingerprint=selected["request_fingerprint"],
        selected_plan_id=selected["selected_plan_id"],
        executed_at=(clock[0] + timedelta(seconds=30)).isoformat(),
        reported_at=(clock[0] + timedelta(seconds=40)).isoformat(),
    )
    return retained, snapshot, basis, worker, journal, receipt, permits


def bundle_for(snapshot):
    return PlanningInputBundle(
        snapshot,
        (),
        (),
        snapshot.captured_at,
        snapshot.captured_at,
        load_replacement_basis=basis_for(snapshot),
    )


def integral(forecast, left, right, field="expected_energy_wh"):
    return sum(
        getattr(i, field)
        * max(timedelta(), min(right, i.ends_at) - max(left, i.starts_at))
        / (i.ends_at - i.starts_at)
        for i in forecast.intervals
    )


@pytest.mark.parametrize("modeled", [False, True])
def test_execution_survives_advice_expiry_and_restart_and_replaces_only_component(
    tmp_path, modeled
):
    retained, snapshot, _, worker, journal, receipt, _ = approved(tmp_path, modeled=modeled)
    before = retained._load_payload()
    assert journal.active(snapshot.captured_at) == []
    assert journal.apply(bundle_for(snapshot)).snapshot == snapshot
    now = snapshot.captured_at + timedelta(seconds=40)
    worker.read_execution = lambda: receipt
    worker.now = lambda: now
    worker.poll_selection()
    restored = AcceptedLoads(journal.path)
    assert len(restored.active(now + timedelta(seconds=121))) == 1
    current = replace(
        snapshot,
        snapshot_id="next-capture",
        captured_at=now,
        daily_charge_context=None,
        capability_snapshot_set=None,
        storage_mode_capability_evidence=None,
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, snapshot_id="next-capture"),
        household_load_forecast=replace(
            snapshot.household_load_forecast, snapshot_id="next-capture"
        ),
    )
    bundle = bundle_for(current)
    if modeled:
        bundle = replace(
            bundle,
            load_replacement_basis=replace(
                bundle.load_replacement_basis, modeled_source_id="c" * 64
            ),
        )
    changed = restored.apply(bundle)
    end = snapshot.captured_at + timedelta(seconds=3630)
    old = integral(current.household_load_forecast, now, end)
    assert integral(changed.snapshot.household_load_forecast, now, end) == pytest.approx(
        old * 0.6 + 100 * 3590 / 3600
    )
    assert changed.controlled_load_summary["accepted_load_removed_wh"] == pytest.approx(old * 0.4)
    assert changed.load_replacement_basis is None
    assert restored.apply(changed) == changed
    assert _planning_input_signature(bundle) != _planning_input_signature(changed)
    assert retained._load_payload() == before
    assert restored.active(end) == []


@pytest.mark.parametrize(
    "fault", ["unknown", "fingerprint", "late_start", "stale", "future", "extra"]
)
def test_invalid_execution_cannot_activate_profile(tmp_path, fault):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at + timedelta(seconds=40)
    if fault == "unknown":
        receipt["request_id"] = "other"
    elif fault == "fingerprint":
        receipt["request_fingerprint"] = "other"
    elif fault == "late_start":
        receipt["executed_at"] = (now + timedelta(seconds=100)).isoformat()
        receipt["reported_at"] = receipt["executed_at"]
        now += timedelta(seconds=100)
    elif fault == "stale":
        now += timedelta(seconds=121)
    elif fault == "future":
        receipt["reported_at"] = (now + timedelta(seconds=1)).isoformat()
    else:
        receipt["energy_wh"] = 0
    assert not journal.observe(receipt, now)
    assert journal.active(now) == []


def test_confirmed_finish_is_monotonic_and_missing_receipt_does_not_cancel(tmp_path):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at + timedelta(seconds=40)
    assert journal.observe(receipt, now)
    assert not journal.observe(None, now + timedelta(seconds=30))
    assert len(journal.active(now + timedelta(seconds=30))) == 1
    ended = dict(receipt, status="finished", reported_at=(now + timedelta(seconds=31)).isoformat())
    assert journal.observe(ended, now + timedelta(seconds=31))
    late = dict(receipt, reported_at=(now + timedelta(seconds=32)).isoformat())
    assert not journal.observe(late, now + timedelta(seconds=32))
    assert AcceptedLoads(journal.path).active(now + timedelta(seconds=33)) == []


@pytest.mark.parametrize("missing", ["basis", "source", "model", "protected_window"])
def test_unproven_attribution_keeps_baseline_and_adds_conservatively(tmp_path, missing):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at + timedelta(seconds=40)
    journal.observe(receipt, now)
    bundle = bundle_for(
        replace(
            snapshot,
            captured_at=now,
            daily_charge_context=None,
            capability_snapshot_set=None,
            storage_mode_capability_evidence=None,
        )
    )
    basis = bundle.load_replacement_basis
    if missing == "basis":
        basis = None
    elif missing == "source":
        basis = replace(basis, source_id="b" * 64)
    elif missing == "model":
        basis = replace(basis, modeled_source_id="c" * 64)
    else:
        basis = replace(basis, starts_at=now + timedelta(hours=2))
    bundle = replace(bundle, load_replacement_basis=basis)
    updated = journal.apply(bundle)
    end = snapshot.captured_at + timedelta(seconds=3630)
    old = integral(bundle.snapshot.household_load_forecast, now, end)
    assert integral(updated.snapshot.household_load_forecast, now, end) == pytest.approx(
        old + 100 * 3590 / 3600
    )
    assert updated.controlled_load_summary["accepted_load_conservative"] is True
    assert updated.controlled_load_summary["accepted_load_removed_wh"] == 0


def test_storage_failure_prevents_permit_and_keeps_existing_profile(tmp_path, monkeypatch):
    _, snapshot, _, worker, journal, receipt, permits = approved(tmp_path)
    now = snapshot.captured_at + timedelta(seconds=40)
    journal.observe(receipt, now)
    existing = copy.deepcopy(journal.active(now))

    def failed(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(journal, "issue", failed)
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"
    assert journal.active(now) == existing


def test_ev_excluded_energy_is_preserved(tmp_path):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at + timedelta(seconds=40)
    journal.observe(receipt, now)
    forecast = replace(
        snapshot.household_load_forecast,
        intervals=tuple(
            replace(i, battery_excluded_energy_wh=i.expected_energy_wh * 0.5)
            for i in snapshot.household_load_forecast.intervals
        ),
    )
    bundle = bundle_for(
        replace(
            snapshot,
            captured_at=now,
            daily_charge_context=None,
            capability_snapshot_set=None,
            storage_mode_capability_evidence=None,
            household_load_forecast=forecast,
        )
    )
    updated = journal.apply(bundle)
    end = snapshot.captured_at + timedelta(seconds=3630)
    assert integral(
        updated.snapshot.household_load_forecast, now, end, "battery_excluded_energy_wh"
    ) == pytest.approx(integral(forecast, now, end, "battery_excluded_energy_wh"))


def reservation(receipt, now, **changes):
    value = {k: receipt[k] for k in ("request_id", "request_fingerprint", "selected_plan_id")}
    value.update(
        contract="hc-energy-reservation:v1",
        status="reserved",
        reported_at=now.isoformat(),
        valid_until=(now + timedelta(seconds=120)).isoformat(),
    )
    value.update(changes)
    return value


def test_reservation_counts_before_start_and_can_be_reassessed_without_double_count(tmp_path):
    from picot.v2.energy_portfolio import assess
    from picot.v2.load_replacement import replace_profile
    from test_daily_main_charge_windows import inputs

    _, snapshot, _, worker, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at
    assert journal.reserve(reservation(receipt, now), now)
    changed = journal.apply(bundle_for(snapshot))
    assert changed.controlled_load_summary["reserved_load_count"] == 1
    assert changed.controlled_load_summary["running_load_count"] == 0
    basis = changed.load_replacement_basis
    assert basis is not None and basis.matches(changed.snapshot)
    request = copy.deepcopy(worker.read())
    request["replacement_basis_id"] = basis.basis_id
    from picot.v2.energy_portfolio import instant

    decoded = [
        dict(start=instant(s["starts_at"]), end=instant(s["ends_at"]), energy=s["energy_wh"])
        for s in request["plans"][0]["slots"]
    ]
    same = replace_profile(changed.snapshot, basis, decoded)
    left, right = now + timedelta(seconds=30), now + timedelta(seconds=3630)
    assert integral(same.household_load_forecast, left, right) == pytest.approx(
        integral(changed.snapshot.household_load_forecast, left, right)
    )
    assert (
        assess(changed.snapshot, request, inputs()["conversion_model"], replacement_basis=basis)[
            "status"
        ]
        == "selected"
    )
    restored = AcceptedLoads(journal.path)
    assert len(restored.planned(now)) == 1
    assert restored.planned(now + timedelta(seconds=120)) == []
    assert journal.observe(receipt, now + timedelta(seconds=40))
    assert journal.planned(now + timedelta(seconds=40)) == []
    assert len(journal.active(now + timedelta(seconds=40))) == 1


def test_reservation_cancel_is_monotonic_but_cannot_remove_running_profile(tmp_path):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at
    assert journal.reserve(reservation(receipt, now), now)
    cancelled = reservation(receipt, now + timedelta(seconds=5), status="cancelled")
    assert journal.reserve(cancelled, now + timedelta(seconds=5))
    assert journal.planned(now + timedelta(seconds=5)) == []
    assert not journal.reserve(
        reservation(receipt, now + timedelta(seconds=6)), now + timedelta(seconds=6)
    )
    assert journal.observe(receipt, now + timedelta(seconds=40))
    journal.reserve(
        reservation(receipt, now + timedelta(seconds=41), status="cancelled"),
        now + timedelta(seconds=41),
    )
    assert len(journal.active(now + timedelta(seconds=41))) == 1


@pytest.mark.parametrize("fault", ["unknown", "stale", "future", "long", "extra"])
def test_invalid_reservation_cannot_change_forecast(tmp_path, fault):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at
    value = reservation(receipt, now)
    if fault == "unknown":
        value["request_fingerprint"] = "other"
    elif fault == "stale":
        now += timedelta(seconds=121)
    elif fault == "future":
        value["reported_at"] = (now + timedelta(seconds=1)).isoformat()
    elif fault == "long":
        value["valid_until"] = (now + timedelta(hours=2)).isoformat()
    else:
        value["energy_wh"] = 0
    assert not journal.reserve(value, now)
    assert journal.apply(bundle_for(snapshot)).snapshot == snapshot


def test_heartbeat_renews_forecast_but_not_start_permission(tmp_path):
    _, snapshot, _, worker, journal, receipt, permits = approved(tmp_path)
    now = snapshot.captured_at
    first = reservation(receipt, now)
    assert journal.reserve(first, now)
    worker.now = lambda: now + timedelta(seconds=90)
    worker.read_reservation = lambda: reservation(receipt, worker.now())
    worker.poll_selection()
    after_expiry = now + timedelta(seconds=130)
    assert len(journal.planned(after_expiry)) == 1
    worker.now = lambda: after_expiry
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"
    assert len(journal.planned(after_expiry)) == 1
    assert journal.active(after_expiry) == []
    assert not journal.reserve(first, after_expiry)
    assert journal.planned(after_expiry + timedelta(seconds=120)) == []


def test_conservative_reservation_does_not_offer_unproven_replacement(tmp_path):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at
    assert journal.reserve(reservation(receipt, now), now)
    bundle = replace(bundle_for(snapshot), load_replacement_basis=None)
    changed = journal.apply(bundle)
    assert changed.controlled_load_summary["reserved_load_count"] == 1
    assert changed.controlled_load_summary["accepted_load_conservative"]
    assert changed.load_replacement_basis is None
    assert integral(
        changed.snapshot.household_load_forecast, now, now + timedelta(hours=2)
    ) == pytest.approx(
        integral(snapshot.household_load_forecast, now, now + timedelta(hours=2)) + 100
    )


def test_known_zero_component_can_be_replaced_but_a_gap_cannot(tmp_path):
    _, snapshot, _, _, journal, receipt, _ = approved(tmp_path)
    now = snapshot.captured_at
    assert journal.reserve(reservation(receipt, now), now)
    bundle = bundle_for(snapshot)
    zero = replace(
        bundle.load_replacement_basis,
        component=tuple(
            replace(i, expected_energy_wh=0) for i in bundle.load_replacement_basis.component
        ),
    )
    changed = journal.apply(replace(bundle, load_replacement_basis=zero))
    assert not changed.controlled_load_summary["accepted_load_conservative"]
    assert changed.load_replacement_basis is not None
    gap = replace(zero, component=zero.component[:-1])
    assert journal.apply(replace(bundle, load_replacement_basis=gap)).load_replacement_basis is None


def test_new_approved_choice_replaces_old_reservation_and_rejects_late_old_cancel(tmp_path):
    from picot.v2.energy_portfolio import fingerprint

    _, snapshot, basis, worker, journal, receipt, permits = approved(tmp_path)
    now = snapshot.captured_at
    assert journal.reserve(reservation(receipt, now), now)
    previous = copy.deepcopy(worker.read_selection())
    request = worker.read()
    request["revision"] += 1
    request["generated_at"] = (now + timedelta(seconds=5)).isoformat()
    request["plans"][0]["slots"][0]["energy_wh"] = 150
    worker.now = lambda: now + timedelta(seconds=5)
    worker.refresh(snapshot, basis)
    assert worker.last_answer["status"] == "selected"
    selected = dict(
        previous,
        revision=request["revision"],
        request_fingerprint=fingerprint(request),
        generated_at=request["generated_at"],
    )
    worker.read_selection = lambda: selected
    worker.poll_selection()
    assert permits[-1]["state"] == "permitted"
    newer = dict(receipt, request_fingerprint=selected["request_fingerprint"])
    assert journal.reserve(
        reservation(newer, now + timedelta(seconds=6)), now + timedelta(seconds=6)
    )
    assert len(journal.planned(now + timedelta(seconds=7))) == 1
    assert journal.planned(now + timedelta(seconds=7))[0]["slots"][0]["energy_wh"] == 150
    assert not journal.reserve(
        reservation(receipt, now + timedelta(seconds=7), status="cancelled"),
        now + timedelta(seconds=7),
    )
    assert len(journal.planned(now + timedelta(seconds=7))) == 1
