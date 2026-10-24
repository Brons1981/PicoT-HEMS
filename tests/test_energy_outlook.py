"""Real retained-route projection to HC, with only HA publication replaced."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from picot.v2.energy_outlook import ENTITY, outlook
from picot.v2.energy_outlook_runtime import EnergyOutlookPublisher
from picot.v2.ha_projection_sink import _ha_attributes
from picot_hc.energy_outlook import read_outlook
from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import scenario


def test_real_projection_reaches_hc_without_mutating_route(tmp_path):
    store, snapshot, plan = scenario(tmp_path, soc=0.9)
    before = store._load_payload()
    answer = outlook(snapshot, inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["retained_plan_id"] == plan.plan_id
    assert answer["approval_required"] and not answer["budgets_additive"]
    assert answer["available_additional_energy_wh"] is None
    assert 1 <= len(answer["slots"]) <= 24
    assert _ha_attributes(answer) == answer  # HA may not silently omit the timeline.
    received = read_outlook(
        {ENTITY: dict(state="ready", attributes=answer)}, snapshot.captured_at.timestamp()
    )
    assert received["status"] == "ready", received
    assert received["projected_minimum_margin_wh"] == min(
        s["storage_margin_wh"] for s in answer["slots"]
    )
    assert store._load_payload() == before


def test_invalid_or_missing_retained_route_clears_outlook(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    missing = replace(snapshot, daily_charge_context=None)
    answer = outlook(missing, inputs()["conversion_model"])
    assert answer["status"] == "blocked"
    assert answer["slots"] == []
    assert (
        read_outlook(
            {ENTITY: dict(state="blocked", attributes=answer)}, snapshot.captured_at.timestamp()
        )["status"]
        == "blocked"
    )


def test_history_summary_reaches_hc_without_becoming_spendable_energy(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    sent = []
    worker = EnergyOutlookPublisher(
        sent.append, lambda s: inputs()["conversion_model"], now=lambda: snapshot.captured_at
    )
    worker.refresh(
        snapshot,
        dict(
            status="history_ready",
            active_forecast_corrected=False,
            total_energy_wh=1000,
            residual_energy_wh=300,
            controlled_energy_wh=700,
        ),
    )
    states = {ENTITY: dict(state="ready", attributes=sent[0])}
    received = read_outlook(states, snapshot.captured_at.timestamp())
    assert received["load_history_status"] == "history_ready"
    assert received["approval_required"] is True
    states[ENTITY]["attributes"]["controlled_load_history"]["controlled_energy_wh"] = 800
    invalid_summary = read_outlook(states, snapshot.captured_at.timestamp())
    assert "load_history_status" not in invalid_summary
    assert invalid_summary["status"] == "ready"


@pytest.fixture
def message(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = outlook(snapshot, inputs()["conversion_model"])
    assert value["status"] == "ready"
    return snapshot, {ENTITY: dict(state="ready", attributes=value)}


@pytest.mark.parametrize(
    "change", ["nan", "bool", "naive", "gap", "double_budget", "truncated", "wrong_margin"]
)
def test_hc_rejects_invalid_or_unsafe_messages(message, change):
    snapshot, states = message
    value = states[ENTITY]["attributes"]
    if change == "nan":
        value["slots"][0]["confidence"] = float("nan")
    if change == "bool":
        value["slots"][0]["grid_import_wh"] = True
    if change == "naive":
        value["generated_at"] = "2026-08-22T10:00:00"
    if change == "gap":
        value["slots"][0]["ends_at"] = value["slots"][0]["starts_at"]
    if change == "double_budget":
        value["budgets_additive"] = True
    if change == "truncated":
        value.pop("slots")
    if change == "wrong_margin":
        value["projected_minimum_margin_wh"] += 100
    assert read_outlook(states, snapshot.captured_at.timestamp())["status"] == "invalid"


def test_hc_expires_and_disconnects_without_reusing_budget(message):
    snapshot, states = message
    now = snapshot.captured_at.timestamp()
    assert read_outlook(states, now + 180)["status"] == "stale"
    assert read_outlook(states, now - 1)["status"] == "invalid"
    assert read_outlook(states, now, connected=False)["status"] == "unavailable"
    assert read_outlook({}, now)["slots"] == []


def test_worker_publishes_without_heating_request_and_rejects_stale_snapshot(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    sent = []
    worker = EnergyOutlookPublisher(
        sent.append, lambda s: inputs()["conversion_model"], now=lambda: snapshot.captured_at
    )
    worker.refresh(snapshot)
    assert len(sent) == 1 and sent[0]["status"] == "ready"
    worker.now = lambda: snapshot.captured_at + timedelta(seconds=121)
    worker.refresh(snapshot)
    assert len(sent) == 1


def test_worker_does_not_publish_result_that_expired_during_computation(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    times = iter([snapshot.captured_at, snapshot.captured_at + timedelta(seconds=121)])
    sent = []
    worker = EnergyOutlookPublisher(
        sent.append, lambda s: inputs()["conversion_model"], now=lambda: next(times)
    )
    worker.refresh(snapshot)
    assert sent == []


def test_worker_failure_is_isolated_and_submission_is_throttled(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    attempts = []

    def failure(value):
        attempts.append(value)
        raise OSError("transport failure")

    worker = EnergyOutlookPublisher(
        failure, lambda s: inputs()["conversion_model"], now=lambda: snapshot.captured_at
    )
    with patch("picot.v2.energy_outlook_runtime.Thread", ImmediateThread):
        worker.submit(snapshot)
        worker.submit(snapshot)
    assert len(attempts) == 1
    assert not worker.lock.locked()
