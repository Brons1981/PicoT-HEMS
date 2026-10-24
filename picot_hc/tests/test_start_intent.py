import copy
from types import SimpleNamespace

import pytest
from picot_hc.core import Store
from picot_hc.delayed_start import candidates
from picot_hc.energy_proposals import Proposals
from picot_hc.start_intent import StartIntent
from test_delayed_start import evidence
from test_energy_proposals import NOW, inputs


def setup(tmp_path):
    startup, steady, standby, sample, view, plan = evidence(tmp_path)
    proposals = Proposals(Store(tmp_path / "hc.sqlite"), SimpleNamespace(submit=lambda value: None))
    proposals.model, proposals.standby = steady, standby
    outlook = inputs()[2]
    proposals.delayed_tick(sample, view, plan, outlook, NOW, startup)
    recipe = proposals.local["candidates"][1]
    selection = SimpleNamespace(
        current=dict(
            request_id=proposals.pending["request_id"],
            selected_plan_id=recipe["plan_id"],
            recipe=copy.deepcopy(recipe),
            valid_until=NOW + 120,
            execution_authorized=False,
        )
    )
    intent = StartIntent(proposals.store)
    intent.capture(selection, proposals, sample, view, plan, NOW)
    return intent, selection, proposals, sample, view, plan, startup, outlook


def test_start_is_fixed_across_new_basis_and_advice_expiry(tmp_path):
    intent, selection, proposals, sample, view, plan, startup, outlook = setup(tmp_path)
    chosen = intent.view(NOW)["heat_starts_at"]
    assert chosen == NOW + 1020
    proposals.fixed_start = intent.check(sample, view, plan, NOW + 150)
    outlook.update(snapshot_id="new", generated_at=NOW + 150, valid_until=NOW + 330)
    for minute in (1, 2, 3):
        proposals.standby.observe(dict(sample, energy_wh=10002.5 + minute / 6), NOW + minute * 60)
    proposals.delayed_tick(sample, view, plan, outlook, NOW + 180, startup)
    assert [p["heat_starts_at"] for p in proposals.local["candidates"]] == [chosen]
    assert intent.view(NOW + 180)["status"] == "needs_assessment"
    assert intent.view(NOW + 180)["execution_authorized"] is False
    selection.current.update(
        request_id=proposals.pending["request_id"],
        recipe=proposals.local["candidates"][0],
        valid_until=NOW + 270,
    )
    intent.capture(selection, proposals, sample, view, plan, NOW + 180)
    assert intent.view(NOW + 180)["heat_starts_at"] == chosen
    assert intent.view(NOW + 180)["status"] == "planned"


@pytest.mark.parametrize(
    "fault", ["schema", "disabled", "manual", "sensor", "floor", "identity", "due", "clock"]
)
def test_changed_conditions_cancel_and_do_not_recapture_same_window(tmp_path, fault):
    intent, selection, proposals, sample, view, plan, _, _ = setup(tmp_path)
    now = NOW + 30
    if fault == "schema":
        view["revision"] += 1
    elif fault == "disabled":
        view["settings"]["enabled"] = False
    elif fault == "manual":
        plan["sources"]["beneden"]["state"] = "heat"
    elif fault == "sensor":
        sample = None
    elif fault == "floor":
        plan["zones"]["beneden"]["target"] = 18
    elif fault == "identity":
        sample["identity"] = "other device"
    elif fault == "due":
        now = NOW + 1020
    elif fault == "clock":
        now = NOW - 1
    assert intent.check(sample, view, plan, now) is None
    assert intent.view(now)["status"] == "cancelled"
    intent.capture(selection, proposals, sample, view, plan, now)
    assert intent.view(now)["status"] == "cancelled"


def test_restart_keeps_record_but_cancels_plan(tmp_path):
    intent, _, proposals, sample, view, plan, _, _ = setup(tmp_path)
    chosen = intent.view(NOW)["heat_starts_at"]
    restored = StartIntent(proposals.store)
    assert restored.check(sample, view, plan, NOW + 30) is None
    assert restored.view(NOW + 30)["heat_starts_at"] == chosen
    assert restored.view(NOW + 30)["status"] == "cancelled"


def test_explicit_schema_change_needs_new_assessment_before_replanning(tmp_path):
    intent, selection, proposals, sample, view, plan, startup, outlook = setup(tmp_path)
    view["revision"] += 1
    assert intent.check(sample, view, plan, NOW + 30) is None
    intent.capture(selection, proposals, sample, view, plan, NOW + 30)
    assert intent.view(NOW + 30)["status"] == "cancelled"
    outlook.update(snapshot_id="new", generated_at=NOW + 30, valid_until=NOW + 210)
    proposals.delayed_tick(sample, view, plan, outlook, NOW + 30, startup)
    selection.current.update(
        request_id=proposals.pending["request_id"],
        recipe=proposals.local["candidates"][0],
        valid_until=NOW + 150,
    )
    intent.capture(selection, proposals, sample, view, plan, NOW + 30)
    assert intent.view(NOW + 30)["status"] == "planned"
    assert intent.view(NOW + 30)["created_at"] == NOW + 30


@pytest.mark.parametrize("fault", ["expired", "withdrawn", "mismatch", "execution"])
def test_invalid_selection_cannot_create_a_start_intent(tmp_path, fault):
    _, selection, proposals, sample, view, plan, _, _ = setup(tmp_path)
    fresh = StartIntent(Store(tmp_path / "fresh.sqlite"))
    if fault == "expired":
        selection.current["valid_until"] = NOW
    elif fault == "withdrawn":
        selection.current = None
    elif fault == "mismatch":
        selection.current["request_id"] = "other"
    else:
        selection.current["execution_authorized"] = True
    fresh.capture(selection, proposals, sample, view, plan, NOW)
    assert fresh.view(NOW)["status"] == "waiting"


def test_fixed_time_cannot_move_to_later_grid_or_before_profile(tmp_path):
    startup, steady, standby, sample, view, plan = evidence(tmp_path)
    assert (
        candidates(
            sample,
            view,
            plan,
            startup.model,
            steady,
            standby.estimate(NOW),
            NOW,
            NOW + 120,
            NOW + 6300,
            fixed_start=NOW + 119,
        )
        == []
    )
