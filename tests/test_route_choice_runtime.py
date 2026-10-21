"""The real runtime callback serializes durable intent and wakes planning."""

import json
from threading import Event

import test_route_choice_store as fixtures

from picot.v2.live_runtime import PlanningResetBarrier, _request_route_choice_and_replan
from picot.v2.web_ui import WebViewStore


def test_runtime_choice_is_pending_until_planner_accepts():
    fixture = fixtures.RouteChoiceStoreTests()
    fixture.setUp()
    try:
        event, web = Event(), WebViewStore()
        web.publish({"run_id": "runtime-test"})
        result = _request_route_choice_and_replan(
            store=fixture.store,
            barrier=PlanningResetBarrier(),
            replan_requested=event,
            web_view_store=web,
            payload={"token": fixture.offer["token"], "action": "pv"},
            requested_at=fixture.at,
        )
        assert result["status"] == "pending"
        assert event.is_set()
        assert fixture.store.active_route_choice(fixture.owner.assignment_id, fixture.at) is None
        assert json.loads(web.latest_json())["route_choices"]["choices"][0]["status"] == "pending"
    finally:
        fixture.doCleanups()


def test_runtime_release_targets_only_selected_assignment():
    fixture = fixtures.RouteChoiceStoreTests()
    fixture.setUp()
    try:
        fixture.accept()
        event = Event()
        result = _request_route_choice_and_replan(
            store=fixture.store,
            barrier=PlanningResetBarrier(),
            replan_requested=event,
            web_view_store=WebViewStore(),
            requested_at=fixture.owner.created_at,
            payload={
                "action": "release",
                "assignment_id": fixture.owner.assignment_id,
                "request_id": "release-runtime",
            },
        )
        assert result["status"] == "released"
        assert event.is_set()
        request = fixture.store.load_daily_recalculation_request()
        assert request.assignment_ids == (fixture.owner.assignment_id,)
        assert request.route_choice_token is None
    finally:
        fixture.doCleanups()
