"""Future planning failure must not grant unbounded execution authority."""
from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_current_proof_does_not_require_future_bridge_to_be_feasible(tmp_path):
    _, snapshot, plan = scenario(tmp_path, soc=0.65)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    assert adapter.committed_execution_invalidity_reasons(
        snapshot=snapshot, plan=plan, conversion_model=conversion,
    )
    until = snapshot.captured_at + timedelta(minutes=15)
    assert adapter.current_execution_invalidity_reasons(
        snapshot=snapshot, plan=plan, conversion_model=conversion, until=until,
    ) == ()


@pytest.mark.parametrize("problem", ["reserve", "capability", "missing_load", "past_bound"])
def test_current_proof_rejects_current_problems(tmp_path, problem):
    _, snapshot, plan = scenario(tmp_path, soc=0.65)
    until = snapshot.captured_at + timedelta(minutes=15)
    if problem == "reserve":
        snapshot = replace(snapshot, current_storage_states=tuple(
            replace(s, current_soc=0.05) for s in snapshot.current_storage_states))
    elif problem == "capability":
        snapshot = replace(snapshot, capability_snapshot_set=replace(
            snapshot.capability_snapshot_set, capabilities=tuple(
                replace(c, supported_primitives=(Primitive.BALANCE_BIDIRECTIONAL,))
                for c in snapshot.capability_snapshot_set.capabilities)))
    elif problem == "missing_load":
        snapshot = replace(snapshot, household_load_forecast=None)
    else:
        until = snapshot.captured_at
    adapter = IndependentDailyReferenceAdapter()
    try:
        issues = adapter.current_execution_invalidity_reasons(
            snapshot=snapshot, plan=plan, conversion_model=inputs()["conversion_model"],
            until=until)
    except ValueError:
        return
    assert issues


def no_winner_run(tmp_path, monkeypatch, *, soc=0.65):
    from picot.domain.evaluation import CandidateValidity
    from picot.planner.evaluation_engine import EvaluationEngine
    from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
    from picot.v2.pipeline import CanonicalPipeline

    store, snapshot, plan = scenario(tmp_path, soc=soc)
    evaluate = EvaluationEngine.evaluate

    def reject(self, candidates, strategy, outcomes, **kwargs):
        # Failure injection at the Candidate -> Evaluation boundary. The real
        # evaluator must produce no winner; no fake execution or store is used.
        outcomes = replace(outcomes, outcomes=tuple(replace(
            o, validity=CandidateValidity.INVALID,
            invalidity_reasons=("supplemental_goal_unreachable:open-goal",),
        ) for o in outcomes.outcomes))
        return evaluate(self, candidates, strategy, outcomes, **kwargs)

    monkeypatch.setattr(EvaluationEngine, "evaluate", reject)
    before = store._path.read_bytes()
    run = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
    ).run(planning_input=snapshot)
    assert run.evaluation.canonical_record.winning_candidate_id is None
    assert store._path.read_bytes() == before
    return store, snapshot, plan, run


def test_failed_replanning_preserves_proven_current_action_without_winner(tmp_path, monkeypatch):
    store, snapshot, plan, run = no_winner_run(tmp_path, monkeypatch)
    due = next(s for s in plan.segments if s.starts_at <= snapshot.captured_at < s.ends_at)
    assert run.evaluation.status == "plan_retained"
    assert run.primitive_boundary.planned_primitive is due.primitive
    assert run.evaluation.winning_candidate_id is None
    assert run.evaluation.execution_continuity.plan_id == plan.plan_id
    assert run.evaluation.execution_continuity.valid_until <= due.ends_at
    assert "supplemental_goal_unreachable:open-goal" in run.evaluation.reason
    assert store.load_active_daily_main_plan("battery") == plan


@pytest.mark.parametrize("change", ["expired", "different_segment"])
def test_committed_dispatch_cannot_outlive_current_proof(tmp_path, change):
    from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime
    from picot.v2.planning_recovery import assess_current_execution

    store, snapshot, plan = scenario(tmp_path, soc=0.65)
    proof = assess_current_execution(
        snapshot, plan, inputs()["conversion_model"],
        ("supplemental_goal_unreachable:open-goal",))
    assert proof is not None and not proof.blocking_reasons
    calls = []
    runtime = CanonicalExecutionRuntime(lambda *args: calls.append(args), commitment_store=store)
    runtime._daily_execution_suspended = False  # Already admitted; isolate evidence expiry.
    runtime._execution_continuity = proof
    if change == "expired":
        snapshot = observed_at(snapshot, proof.valid_until)
    else:
        runtime._execution_continuity = replace(proof, segment_id="other-segment")
    result = runtime.advance_committed_boundary(snapshot, execution_enabled=True)
    assert result.status == "blocked"
    assert result.failure_reason == "current_execution_proof_expired_or_replaced"
    assert not calls


def test_fresh_proof_can_renew_without_mutating_goals(tmp_path):
    from picot.v2.planning_recovery import assess_current_execution

    store, snapshot, plan = scenario(tmp_path, soc=0.65)
    before = store._path.read_bytes()
    first = assess_current_execution(
        snapshot, plan, inputs()["conversion_model"],
        ("supplemental_goal_unreachable:open-goal",))
    later = observed_at(snapshot, first.valid_until)
    renewed = assess_current_execution(
        later, plan, inputs()["conversion_model"],
        ("supplemental_goal_unreachable:open-goal",))
    assert renewed is not None and not renewed.blocking_reasons
    assert renewed.assessed_at == first.valid_until
    assert renewed.valid_until > first.valid_until
    assert renewed.unresolved_reasons == first.unresolved_reasons
    assert store._path.read_bytes() == before


def observed_at(snapshot, at):
    return replace(
        snapshot, captured_at=at,
        daily_charge_context=replace(snapshot.daily_charge_context, restored_at=at),
        capability_snapshot_set=replace(snapshot.capability_snapshot_set, captured_at=at),
        storage_mode_capability_evidence=replace(
            snapshot.storage_mode_capability_evidence, captured_at=at)
            if snapshot.storage_mode_capability_evidence is not None else None,
        current_storage_states=tuple(replace(s, measured_at=at)
                                     for s in snapshot.current_storage_states),
    )


@pytest.mark.parametrize("reason", ["technical_simulation_failure", "unknown_rejection"])
def test_unclassified_planning_failure_cannot_grant_continuity(tmp_path, reason):
    from picot.v2.planning_recovery import assess_current_execution

    _, snapshot, plan = scenario(tmp_path, soc=0.65)
    proof = assess_current_execution(snapshot, plan, inputs()["conversion_model"], (reason,))
    assert "planning_failure_not_eligible_for_current_continuity" in proof.blocking_reasons


def test_expired_continuity_requests_fresh_planning():
    from datetime import UTC, datetime

    from picot.runtime.runtime_monitor import RuntimeMonitorSession
    from picot.v2.live_runtime import _observe_execution_status

    monitor = RuntimeMonitorSession()
    at = datetime(2026, 10, 26, 13, 15, tzinfo=UTC)
    _observe_execution_status(
        monitor, status="replan_required", source_reference="retained-plan",
        observed_at=at, observation_id="expired-proof",
    )
    assert monitor.state.replan_required
    assert monitor.observe((), now=at).fresh_snapshot_required
