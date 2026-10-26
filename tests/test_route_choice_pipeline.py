"""Consent is committed only through real candidate evaluation and plan binding."""

from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_route_optimisation import fresh

from picot.domain.evaluation import CandidateValidity
from picot.v2 import mep_canonical_pipeline as mep
from picot.v2.route_choice_policy import main_signature, respects_choice


def offer_future_route(tmp_path, monkeypatch):
    captured = []
    original = mep.prepare_offer

    def capture(portfolio, winner, owner, at):
        captured.append((portfolio, winner))
        return original(portfolio, winner, owner, at)

    monkeypatch.setattr(mep, "prepare_offer", capture)
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    portfolio, winner = captured[-1]
    valid = {
        o.candidate_id
        for o in portfolio.outcome_set.outcomes
        if o.validity is CandidateValidity.VALID
    }
    alternative = next(
        s
        for s in portfolio.sources
        if s.window is not None
        and s.candidate_id != winner
        and s.candidate_id in valid
        and any(
            segment.starts_at > first.planning_input.captured_at + timedelta(minutes=10)
            for segment in s.window.main_segments
        )
    )
    offer = store.offer_route_choice(
        assignment_id=owner.assignment_id,
        plan_id=owner.route_plan_id,
        revision=owner.revision,
        created_at=first.planning_input.captured_at,
        expires_at=first.planning_input.captured_at + timedelta(minutes=5),
        offer={"alternative": {"main_signature": main_signature(alternative.window)}},
    )
    return store, pipeline, recover, first, owner, offer


def test_user_choice_reaches_real_plan_binder_and_release(tmp_path, monkeypatch):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="consent")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    run = pipeline.run(planning_input=recover(source))
    record = store.route_choice_status(source.captured_at)["choices"][-1]
    assert record["status"] == "selected", (record, run.evaluation.reason)
    plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    assert plan.plan_id == record["accepted_plan_id"]
    assert plan.plan_id == run.execution_plan_set.plans[0].plan_id
    assert store.load_daily_assignments()[0].revision_reason.value == "explicit_user_route_choice"
    assert store.load_daily_recalculation_request() is None
    again = pipeline.run(planning_input=recover(source))
    assert again.evaluation.status == "plan_retained"
    store.release_route_choice(
        assignment_id=owner.assignment_id,
        requested_at=source.captured_at,
        request_id="return-control",
    )
    released = pipeline.run(planning_input=recover(fresh(source, tag="released")))
    assert released.execution_plan_set.plans
    assert store.active_route_choice(owner.assignment_id, source.captured_at) is None
    assert store.load_daily_recalculation_request() is None


def test_disappeared_alternative_rejects_without_losing_plan(tmp_path, monkeypatch):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    old_plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    source = fresh(first.planning_input, tag="changed")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    # A once-offered signature is no longer generated from current input.
    monkeypatch.setattr(mep, "requested_candidates", lambda portfolio, record, at: set())
    run = pipeline.run(planning_input=recover(source))
    record = store.route_choice_status(source.captured_at)["choices"][-1]
    assert record["status"] == "rejected"
    assert store.load_active_daily_main_plan(owner.execution_scope_id) == old_plan
    assert store.load_daily_recalculation_request() is None
    assert "result_not_saved" not in (run.evaluation.reason or "")


def test_physical_shortfall_can_repair_but_keeps_choice_and_explains_it(tmp_path, monkeypatch):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="consent-repair")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    pipeline.run(planning_input=recover(source))
    chosen = store.active_route_choice(owner.assignment_id, source.captured_at)
    assert chosen is not None
    changed = fresh(source, pv_factor=0.0, soc=0.3, tag="real-shortfall")
    run = pipeline.run(planning_input=recover(changed))
    record = store.active_route_choice(owner.assignment_id, changed.captured_at)
    assert record is not None
    assert record["accepted_plan_id"] == chosen["accepted_plan_id"]
    assert record["last_notice"]["key"].startswith("repair:"), run.evaluation.reason
    assert (
        store.load_active_daily_main_plan(owner.execution_scope_id).plan_id
        != chosen["accepted_plan_id"]
    )


def test_economic_recheck_does_not_add_grid_outside_choice(tmp_path, monkeypatch):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="consent-economic")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    pipeline.run(planning_input=recover(source))
    chosen = store.active_route_choice(owner.assignment_id, source.captured_at)
    assert chosen is not None
    changed = fresh(source, tag="economic-recheck")
    store.request_daily_recalculation(request_id="review", requested_at=changed.captured_at)
    pipeline.run(planning_input=recover(changed))
    plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    assert respects_choice(plan, chosen, changed.captured_at)
    assert store.active_route_choice(owner.assignment_id, changed.captured_at) is not None


def test_planning_uses_captured_choice_without_rereading_store(tmp_path, monkeypatch):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="captured-choice")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    captured = recover(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("planning reread mutable route consent")

    monkeypatch.setattr(store, "pending_route_choice", forbidden)
    monkeypatch.setattr(store, "active_route_choice", forbidden)
    run = pipeline.run(planning_input=captured)
    record = store.route_choice_status(source.captured_at)["choices"][-1]
    assert record["status"] == "selected", run.evaluation.reason
    assert (store.load_active_daily_main_plan(owner.execution_scope_id).plan_id
            == record["accepted_plan_id"])


def test_capture_is_immutable_and_release_requires_new_snapshot(tmp_path, monkeypatch):
    from dataclasses import FrozenInstanceError, asdict
    from types import SimpleNamespace

    from picot.v2.live_runtime import _planning_input_signature

    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="capture-release")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    pipeline.run(planning_input=recover(source))
    captured = recover(source)
    choice = captured.daily_charge_context.route_choices[0]
    before = asdict(captured.daily_charge_context)
    with pytest.raises(FrozenInstanceError):
        choice.status = "released"
    detached = choice.policy_record()
    detached["offer"]["alternative"]["main_signature"].clear()
    assert choice.main_signature
    store.release_route_choice(assignment_id=owner.assignment_id,
        requested_at=source.captured_at, request_id="release-after-capture")
    assert asdict(captured.daily_charge_context) == before
    newer = recover(source)
    assert newer.daily_charge_context.route_choices == ()
    def signature(snapshot):
        return _planning_input_signature(SimpleNamespace(
            snapshot=snapshot, facts=(), controlled_load_summary=None))
    assert signature(captured) != signature(newer)


def test_missing_captured_request_cannot_choose_an_unrequested_route(tmp_path, monkeypatch):
    from dataclasses import replace

    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="missing-consent")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    captured = recover(source)
    old_plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    incomplete = replace(captured, daily_charge_context=replace(
        captured.daily_charge_context, route_choices=()))
    run = pipeline.run(planning_input=incomplete)
    assert run.evaluation.winning_candidate_id is None
    assert store.load_active_daily_main_plan(owner.execution_scope_id) == old_plan
    assert store.route_choice_status(source.captured_at)["choices"][-1]["status"] == "rejected"


def test_captured_selected_choice_survives_restart_and_ends_with_owner(tmp_path, monkeypatch):
    from dataclasses import replace
    from zoneinfo import ZoneInfo

    from picot.v2.live_runtime import _restore_daily_charge_context
    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="restart-consent")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    pipeline.run(planning_input=recover(source))
    captured = recover(source)
    restarted = ActivePlanCommitmentStore(store._path)
    again = _restore_daily_charge_context(replace(source, daily_charge_context=None), restarted,
                                          local_timezone=ZoneInfo("UTC"))
    assert again.daily_charge_context.route_choices == captured.daily_charge_context.route_choices
    assignments = again.daily_charge_context.assignments
    assert restarted.planning_route_choices(assignments, owner.ends_at) == ()


@pytest.mark.parametrize("corruption", ["missing_signature", "mutable_intent"])
def test_invalid_stored_consent_blocks_capture_instead_of_dropping_choice(
    tmp_path, monkeypatch, corruption,
):
    store, pipeline, recover, first, owner, offer = offer_future_route(tmp_path, monkeypatch)
    source = fresh(first.planning_input, tag="invalid-consent")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    payload = store._load_payload()
    alternative = payload["route_choices"][offer["token"]]["offer"]["alternative"]
    if corruption == "missing_signature":
        del alternative["main_signature"]
    else:
        alternative["main_signature"][0][2] = ["grid_requirement"]
    store._write(payload)
    captured = recover(source)
    assert captured.daily_charge_context.status == "blocked"
    assert captured.daily_charge_context.reason == "stored route choice input is invalid"
