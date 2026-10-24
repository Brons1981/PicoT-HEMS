import copy

import pytest
from picot_hc.core import Store
from picot_hc.startup_energy import StartupEnergy
from picot_hc.warmup_energy import WarmupEnergy
from test_energy_proposals import NOW, sample


def inputs(now):
    view = dict(
        revision=1,
        settings=dict(enabled=True, learning_enabled=True),
        next=dict(starts_at=now + 3600, target=20),
        current=None,
    )
    plan = dict(
        enabled=True,
        preheating=True,
        desired=dict(beneden=20),
        owned={},
        learning_status=dict(phase="preheat"),
        sources=dict(beneden=dict(state="off", pending=False, temperature=20)),
    )
    command = dict(
        id=str(now),
        source="beneden",
        field="heating",
        value=20,
        origin="schedule",
        before=dict(mode="off"),
        created=now,
        sent=now,
        status="awaiting_feedback",
    )
    return view, plan, command


def run(model, now, fault=None):
    view, plan, command = inputs(now)
    initial = dict(sample(), indoor=18, power_w=0)
    model.prepare(initial, view, plan, ("beneden", "heating", 20), now)
    plan["owned"] = dict(beneden=dict(command=command["id"]))
    used, previous = 0, 0
    for minute in range(35):
        power = 0 if minute == 0 else 300 if minute == 1 else 1200
        if minute:
            used += (previous + power) / 2 / 60
        previous = power
        s = dict(
            initial,
            power_w=power,
            energy_wh=10000 + used,
            indoor=min(20, 18 + max(0, minute - 2) / 15),
        )
        if minute >= 2:
            command["status"] = "confirmed"
            plan["sources"]["beneden"]["state"] = "heat"
        if fault == "manual":
            command["origin"] = "manual"
        if fault == "failed" and minute == 1:
            command["status"] = "failed"
        if fault == "gap" and minute == 10:
            s = None
        if fault == "schema" and minute >= 10:
            view["revision"] = 2
        if fault == "unconfirmed":
            command["status"] = "awaiting_feedback"
        if fault == "lost_heat" and minute == 10:
            plan["sources"]["beneden"]["state"] = "off"
        model.observe(s, view, plan, [command], now + minute * 60)


def test_full_start_includes_waiting_energy_and_persists_separately(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = StartupEnergy(store)
    for day in (3, 2, 1):
        run(model, NOW - day * 86400)
    assert len(model.model.records) == 3
    record = model.model.records[-1]
    assert record["used_wh"] == pytest.approx(655)
    assert record["duration_seconds"] == 2040
    assert record["confirmation_delay_seconds"] == 120
    assert WarmupEnergy(store).records == []
    restored = StartupEnergy(store)
    estimate = restored.view(dict(sample(), indoor=18), NOW)
    assert estimate["energy_wh"] == pytest.approx(818.75)
    assert estimate["duration_seconds"] == 2550
    assert estimate["completed_sessions"] == 3
    assert not estimate["execution_authorized"]


@pytest.mark.parametrize("fault", ["manual", "failed", "gap", "schema", "unconfirmed", "lost_heat"])
def test_invalid_attempts_never_become_complete(tmp_path, fault):
    model = StartupEnergy(Store(tmp_path / "hc.sqlite"))
    run(model, NOW, fault=fault)
    assert model.model.records == []


def test_no_off_baseline_or_restart_cannot_invent_full_start(tmp_path):
    store = Store(tmp_path / "hc.sqlite")
    model = StartupEnergy(store)
    view, plan, command = inputs(NOW)
    s = dict(sample(), indoor=18)
    plan["owned"] = dict(beneden=dict(command=command["id"]))
    model.observe(s, view, plan, [command], NOW)
    assert model.model.session is None
    model.prepare(s, view, plan, ("beneden", "heating", 20), NOW)
    model.observe(s, view, plan, [command], NOW)
    assert model.model.session is not None
    restarted = StartupEnergy(store)
    restarted.observe(s, view, plan, [command], NOW + 60)
    assert restarted.model.session is None
    changed = copy.deepcopy(plan)
    changed["sources"]["beneden"]["state"] = "heat"
    restarted.prepare(s, view, changed, ("beneden", "heating", 20), NOW + 60)
    assert restarted.baseline is None


def test_stale_or_post_command_baseline_is_rejected(tmp_path):
    model = StartupEnergy(Store(tmp_path / "hc.sqlite"))
    view, plan, command = inputs(NOW)
    s = dict(sample(), indoor=18)
    plan["owned"] = dict(beneden=dict(command=command["id"]))
    model.prepare(s, view, plan, ("beneden", "heating", 20), NOW)
    model.observe(s, view, plan, [command], NOW + 91)
    assert model.model.session is None
    model.prepare(s, view, plan, ("beneden", "heating", 20), NOW + 60)
    model.observe(s, view, plan, [command], NOW + 60)
    assert model.model.session is None
    assert model.model.records == []
