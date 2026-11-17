"""Automatic planning continues when an old installation has route-choice records."""

from datetime import timedelta

from test_daily_main_active_pipeline import setup
from test_daily_main_route_optimisation import fresh


def test_automatic_planner_commits_without_creating_a_manual_offer(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    assert first.execution_plan_set.plans, first.evaluation.reason
    assert store.route_choice_status(first.planning_input.captured_at) == {"choices": []}


def test_upgrade_retires_pending_manual_choice_and_keeps_the_plan(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    plan = store.load_active_daily_main_plan(owner.execution_scope_id)
    offer = store.offer_route_choice(
        assignment_id=owner.assignment_id,
        plan_id=owner.route_plan_id,
        revision=owner.revision,
        created_at=first.planning_input.captured_at,
        expires_at=first.planning_input.captured_at + timedelta(minutes=5),
        offer={"alternative": {"main_signature": []}},
    )
    source = fresh(first.planning_input, tag="legacy-choice")
    store.request_route_choice(token=offer["token"], action="pv", requested_at=source.captured_at)
    captured = recover(source)
    assert captured.daily_charge_context.route_choices == ()
    run = pipeline.run(planning_input=captured)
    assert run.execution_plan_set.plans[0].plan_id == plan.plan_id
    assert store.load_active_daily_main_plan(owner.execution_scope_id) == plan
    assert store.load_daily_recalculation_request() is None
    record = store.route_choice_status(source.captured_at)["choices"][0]
    assert record["status"] == "rejected"
    assert record["reason"] == "manual_route_choice_removed"
