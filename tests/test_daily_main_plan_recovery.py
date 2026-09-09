"""Crash/restart checks at the canonical Plan Store boundary, not HA execution."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from test_daily_main_charge_selection import evaluate, portfolio_fixture

from picot.domain.execution_plan import ExecutionPlanLifecycle
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


@pytest.fixture(scope="module")
def selected_route():
    snapshot, assignment, _, _, portfolio = portfolio_fixture()
    result = evaluate(snapshot, portfolio)
    source = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    (plan,) = ExecutionPlanBuilder().build(
        result, created_at=snapshot.captured_at, fallback_policy_id="guarded-nom"
    ).plans
    return assignment, plan, source.window


def test_restart_restores_exact_plan_without_reselecting(tmp_path, selected_route):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    restarted = ActivePlanCommitmentStore(path)
    assert restarted.load_daily_main_plan(bound.assignment_id) == plan
    assert restarted.load_daily_assignments() == (bound,)
    # Recovery is not execution admission. The normal execution guards still
    # have to validate the proposed plan against current observations.
    recovered = restarted.load_daily_main_plan(bound.assignment_id)
    assert recovered.lifecycle is ExecutionPlanLifecycle.PROPOSED
    with patch.object(restarted, "_write", side_effect=AssertionError("duplicate write")):
        assert restarted.bind_daily_main_plan(plan=plan, window=window) == bound


def test_failed_atomic_replace_cannot_leave_bound_goal_without_route(tmp_path, selected_route):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    before = path.read_bytes()
    with patch("picot.v2.plan_commitment_store.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            store.bind_daily_main_plan(plan=plan, window=window)
    restarted = ActivePlanCommitmentStore(path)
    assert path.read_bytes() == before
    assert restarted.load_daily_assignments() == (assignment,)
    assert restarted.load_daily_main_plan(assignment.assignment_id) is None
    # Retry recovers both records together, without a second daily identity.
    bound = restarted.bind_daily_main_plan(plan=plan, window=window)
    assert restarted.load_daily_main_plan(bound.assignment_id) == plan


def test_same_plan_id_cannot_silently_change_execution_content(tmp_path, selected_route):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    store.bind_daily_main_plan(plan=plan, window=window)
    before = path.read_bytes()
    modified = replace(plan, fallback_policy_id="different-policy")
    with pytest.raises(ValueError, match="immutable"):
        store.bind_daily_main_plan(plan=modified, window=window)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "damage", ["missing", "wrong_plan", "wrong_segment", "bad_enum", "bad_type", "wrong_evidence"]
)
def test_corrupt_route_is_explicit_error_and_never_recreated(tmp_path, selected_route, damage):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    payload = json.loads(path.read_text())
    record = payload["daily_execution_plans"][assignment.assignment_id]
    if damage == "missing":
        del payload["daily_execution_plans"]
    elif damage == "wrong_plan":
        record["plan_id"] = "some-other-plan"
    elif damage == "wrong_segment":
        owned = {s.segment_id for s in bound.main_segments}
        for segment in record["segments"]:
            if segment["segment_id"] in owned:
                segment["segment_id"] += "-changed"
    elif damage == "bad_enum":
        record["segments"][0]["primitive"] = "unknown-mode"
    elif damage == "wrong_evidence":
        record["evaluation_id"] = "another-evaluation"
    else:
        payload["daily_execution_plans"] = []
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="refusing to invent"):
        ActivePlanCommitmentStore(path).load_daily_main_plan(assignment.assignment_id)
    assert path.read_bytes() == before
    assert store.load_daily_assignments() == (bound,)


def test_completion_and_route_survive_restart_and_execution_reset(tmp_path, selected_route):
    assignment, plan, window = selected_route
    path = tmp_path / "plans.json"
    store = ActivePlanCommitmentStore(path)
    store.save_daily_assignment(assignment)
    bound = store.bind_daily_main_plan(plan=plan, window=window)
    main = bound.main_segments[0]
    completed = bound.observe_completion(
        measured_at=main.starts_at, soc=1.0, evidence_id="actual-main-soc",
        plan_id=plan.plan_id, segment_id=main.segment_id, execution_allowed=True,
    )
    assert completed.completed_at == main.starts_at
    store.save_daily_assignment(completed)
    store.clear_all()
    restarted = ActivePlanCommitmentStore(path)
    assert restarted.load_daily_assignments() == (completed,)
    assert restarted.load_daily_main_plan(assignment.assignment_id) == plan
    assert restarted.bind_daily_main_plan(plan=plan, window=window) == completed


def test_unknown_assignment_is_not_confused_with_unplanned_day(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        ActivePlanCommitmentStore(tmp_path / "plans.json").load_daily_main_plan("unknown-day")
