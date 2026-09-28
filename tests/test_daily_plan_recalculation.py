"""An explicit user request revises native daily routes without erasing goals."""

import json
from dataclasses import replace
from functools import partial
from threading import Event, Thread
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_daily_main_horizon_retention import stored
from test_daily_main_horizon_retention import two_days as two_days
from test_daily_main_load_protection import bound_grid
from test_daily_main_route_optimisation import fresh
from test_daily_material_replanning import bundle
from test_market_revision_comparison import scenario

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.runtime import RuntimeObservationKind
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.live_runtime import (
    PlanningResetBarrier,
    _request_daily_recalculation_and_replan,
    _restore_daily_charge_context,
)
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.material_replanning import MaterialReplanningObservationProducer
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.web_ui import WebViewStore, _build_planning_status, create_web_server


def test_request_recalculates_bound_route_and_is_consumed_once(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    original_plan = store.load_active_daily_main_plan("battery")
    source = fresh(first.planning_input, tag="manual")
    web = WebViewStore()
    web.publish({"run_id": first.planning_input.run_id})
    event = Event()
    callback = partial(
        _request_daily_recalculation_and_replan,
        store=store, barrier=PlanningResetBarrier(), replan_requested=event,
        web_view_store=web, requested_at=source.captured_at,
    )
    server = create_web_server(web, host="127.0.0.1", port=0,
                               reset_planning=lambda reset_id: callback(request_id=reset_id))
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(Request(
            f"http://127.0.0.1:{server.server_port}/api/planning/reset",
            data=b'{"reset_id":"manual-test"}',
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=2) as response:
            request = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert request["status"] == "pending"
    assert event.is_set()
    assert json.loads(web.latest_json())["planning_recalculation"]["status"] == "pending"
    assert store.load_daily_assignments() == (owner,)
    assert store.load_active_daily_main_plan("battery") == original_plan
    result = pipeline.run(planning_input=recover(source))
    assert result.candidate_set.candidates
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    revised = store.load_daily_assignments()[0]
    assert revised.assignment_id == owner.assignment_id
    assert revised.created_at == owner.created_at
    assert revised.revision == owner.revision + 1
    assert revised.completed_at is None
    assert store.daily_recalculation_status()["status"] == "completed"
    web.publish_planning_recalculation(store.daily_recalculation_status())
    web.publish({"run_id": result.planning_input.run_id})
    assert json.loads(web.latest_json())["planning_recalculation"]["status"] == "completed"
    before = (tmp_path / "plans.json").read_bytes()
    again = pipeline.run(planning_input=recover(source))
    assert again.evaluation.status == "plan_retained"
    assert not again.candidate_set.candidates
    assert (tmp_path / "plans.json").read_bytes() == before


def test_pending_request_survives_restart_and_duplicate_clicks(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    source = fresh(first.planning_input)
    request = store.request_daily_recalculation(request_id="once", requested_at=source.captured_at)
    saved = store._path.read_bytes()
    store = ActivePlanCommitmentStore(store._path)
    assert store.request_daily_recalculation(
        request_id="second-click", requested_at=source.captured_at,
    ) == request
    assert store._path.read_bytes() == saved
    restored = _restore_daily_charge_context(source, store, local_timezone=ZoneInfo("UTC"))
    assert restored.daily_charge_context.recalculation_request.request_id == "once"
    monitor_input = MaterialReplanningObservationProducer(
        history=HouseholdLoadHistoryStore(tmp_path / "load.json"),
        conversion_model=lambda snapshot: inputs()["conversion_model"],
    )
    observed = monitor_input.observe(bundle(restored))[0]
    assert observed.kind is RuntimeObservationKind.COMMITMENT_CHANGED
    # Restart/poll without an in-memory button event still offers the durable request to Monitor.
    assert monitor_input.observe(bundle(restored))[0].new_value == "explicit_user_recalculation"
    pipeline = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]))
    result = pipeline.run(planning_input=restored)
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    saved = store._path.read_bytes()
    assert store.request_daily_recalculation(
        request_id="once", requested_at=source.captured_at,
    )["status"] == "completed"
    # A stale calculation cannot rebind the old revision or consume a second request.
    pipeline.run(planning_input=restored)
    assert store._path.read_bytes() == saved
    previous_result = store.daily_recalculation_status()
    store.request_daily_recalculation(request_id="later", requested_at=source.captured_at)
    assert store._load_payload()["daily_recalculation_history"]["once"] == previous_result


@pytest.mark.parametrize("failure", ["missing_prices", "unreachable", "builder_failure"])
def test_failed_request_does_not_erase_existing_goal_or_plan(tmp_path, monkeypatch, failure):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    initial = recover()
    if failure == "builder_failure":
        initial = replace(initial, household_load_forecast=replace(
            initial.household_load_forecast, intervals=tuple(
                replace(i, expected_energy_wh=i.expected_energy_wh / 4)
                for i in initial.household_load_forecast.intervals)))
    first = pipeline.run(planning_input=initial)
    source = fresh(first.planning_input)
    if failure == "missing_prices":
        source = replace(source, price_points=())
    elif failure == "unreachable":
        source = fresh(source, pv_factor=0, soc=0.1)
        source = replace(source, storage_physical_limits=tuple(
            replace(limit, maximum_charge_input_power_w=1)
            for limit in source.storage_physical_limits))
    else:
        def reject(*args, **kwargs):
            raise ValueError("injected builder rejection")
        monkeypatch.setattr(ExecutionPlanBuilder, "build", reject)
    store.request_daily_recalculation(request_id="failed", requested_at=source.captured_at)
    before = store._load_payload()
    result = pipeline.run(planning_input=recover(source))
    assert store.daily_recalculation_status()["status"] == "failed"
    after = store._load_payload()
    assert {k: v for k, v in after.items() if k != "daily_recalculation"} == {
        k: v for k, v in before.items() if k != "daily_recalculation"}
    assert not store.load_daily_recalculation_request()
    assert result.evaluation.status == (
        "plan_retained" if failure == "builder_failure" else "fallback_active")
    if failure == "builder_failure":
        view = _build_planning_status(result)
        original = first.execution_plan_set.plans[0]
        assert view["chosen_plan"]["plan_id"] == original.plan_id
        assert view["chosen_plan"]["candidate_id"] == original.winning_candidate_id
        assert view["chosen_plan"]["energy_path_id"] == original.winning_energy_path_id
        # Never label the unpublished replacement as the retained plan.
        assert not view["soc_timeline"]


def test_atomic_publication_failure_preserves_plan_and_pending_request(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    source = fresh(first.planning_input)
    store.request_daily_recalculation(request_id="disk-failure", requested_at=source.captured_at)
    before = store._path.read_bytes()
    with monkeypatch.context() as fail:
        def reject(*args, **kwargs):
            raise OSError("disk failure")
        fail.setattr("picot.v2.plan_commitment_store.os.replace", reject)
        pipeline.run(planning_input=recover(source))
    assert store._path.read_bytes() == before
    assert store.daily_recalculation_status()["status"] == "pending"
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert store.daily_recalculation_status()["status"] == "completed"


def test_absent_current_execution_is_reported_without_crashing_or_erasing(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    source = fresh(first.planning_input)
    store.request_daily_recalculation(request_id="absent", requested_at=source.captured_at)
    restored = recover(source)
    restored = replace(restored, daily_charge_context=replace(
        restored.daily_charge_context, active_main_plan_ids=()))
    owners = store.load_daily_assignments()
    plan = store.load_active_daily_main_plan("battery")
    result = pipeline.run(planning_input=restored)
    assert result.evaluation.status == "fallback_active"
    assert store.daily_recalculation_status()["status"] == "failed"
    assert store.load_daily_assignments() == owners
    assert store.load_active_daily_main_plan("battery") == plan


def test_completed_goal_is_not_reopened_by_button(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    owner = store.load_daily_assignments()[0]
    segment = owner.main_segments[0]
    completed = owner.observe_completion(
        measured_at=segment.starts_at, soc=1, evidence_id="measured-full",
        plan_id=owner.route_plan_id, segment_id=segment.segment_id, execution_allowed=True,
    )
    store.save_daily_assignment(completed)
    before = store._load_payload()
    event = Event()
    result = _request_daily_recalculation_and_replan(
        store=store, barrier=PlanningResetBarrier(), replan_requested=event,
        web_view_store=WebViewStore(), request_id="completed",
        requested_at=segment.starts_at,
    )
    assert result["status"] == "not_applicable"
    assert not event.is_set()
    assert store.load_daily_assignments() == (completed,)
    assert {k: v for k, v in store._load_payload().items() if k != "daily_recalculation"} == before


def test_recalculation_preserves_market_and_completed_other_goal(tmp_path):
    store, source, original = scenario(tmp_path, soc=1.0)
    before = store._load_payload()
    owners = store.load_daily_assignments()
    requested = store.request_daily_recalculation(
        request_id="market", requested_at=source.captured_at,
    )
    expected = tuple(a for a in owners if a.completed_at is None)
    assert requested["pending_assignment_ids"] == [a.assignment_id for a in expected]
    pipeline = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]))
    for index, owner in enumerate(expected):
        source = fresh(source, tag=f"market-{index}")
        restored = _restore_daily_charge_context(source, store,
                                                  local_timezone=ZoneInfo("Europe/Amsterdam"))
        others = tuple(a for a in store.load_daily_assignments()
                       if a.assignment_id != owner.assignment_id)
        result = pipeline.run(planning_input=restored)
        assert result.evaluation.status == "winner_selected", result.evaluation.reason
        assert tuple(a for a in store.load_daily_assignments()
                     if a.assignment_id != owner.assignment_id) == others
        revised = next(a for a in store.load_daily_assignments()
                       if a.assignment_id == owner.assignment_id)
        assert revised.revision == owner.revision + 1
    after = store._load_payload()
    assert store.daily_recalculation_status()["status"] == "completed"
    assert after["market_daily_assignments"] == before["market_daily_assignments"]
    for assignment_id, binding in before["market_plan_bindings"].items():
        revised = after["market_plan_bindings"][assignment_id]
        assert revised["expected_export_wh"] == binding["expected_export_wh"]
        assert revised["cancelled_export_wh"] == binding["cancelled_export_wh"]
    assert after.get("market_execution_progress") == before.get("market_execution_progress")
    assert after["execution_plans"][original.plan_id] == before["execution_plans"][original.plan_id]


@pytest.mark.parametrize("both_shortfall", [False, True])
def test_two_native_days_recalculate_in_order_without_altering_other_owner(
    tmp_path, two_days, both_shortfall,
):
    case = two_days
    store = stored(tmp_path, case)
    store.bind_daily_main_plan(
        plan=case["second_set"].plans[0], window=case["second_window"], activate=True,
    )
    source = fresh(case["source"])
    if both_shortfall:
        source = fresh(source, pv_factor=0, soc=0.1, tag="both-shortfall")
    owners = store.load_daily_assignments()
    assert len(owners) == 2 and all(a.completed_at is None for a in owners)
    store.request_daily_recalculation(request_id="two-days", requested_at=source.captured_at)
    pipeline = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(case["conversion"]))
    for index, owner in enumerate(owners):
        source = fresh(source, tag=f"day-{index}")
        restored = _restore_daily_charge_context(source, store,
                                                 local_timezone=ZoneInfo("Europe/Amsterdam"))
        others = tuple(a for a in store.load_daily_assignments()
                       if a.assignment_id != owner.assignment_id)
        result = pipeline.run(planning_input=restored)
        assert result.evaluation.status == "winner_selected", result.evaluation.reason
        assert tuple(a for a in store.load_daily_assignments()
                     if a.assignment_id != owner.assignment_id) == others
        request = store.daily_recalculation_status()
        assert request["status"] == ("pending" if index == 0 else "completed")
        revised = next(a for a in store.load_daily_assignments()
                       if a.assignment_id == owner.assignment_id)
        assert revised.revision == owner.revision + 1


def test_button_preserves_protected_ongoing_grid_charge(tmp_path, monkeypatch):
    source, grid = bound_grid(tmp_path, monkeypatch)
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.request_daily_recalculation(request_id="charging", requested_at=source.captured_at)
    source = _restore_daily_charge_context(source, store, local_timezone=ZoneInfo("UTC"))
    pipeline = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]))
    run = pipeline.run(planning_input=source)
    assert run.evaluation.status == "winner_selected", run.evaluation.reason
    plan = store.load_active_daily_main_plan("battery")
    assert all(s.primitive is ExecutionPrimitive.CHARGE_AT_POWER for s in plan.segments
               if s.starts_at < grid.ends_at and s.ends_at > source.captured_at)
