"""Exercise restart and recovery as a sequence, using real plans and storage."""

from dataclasses import replace

from test_current_execution_recovery import observed_at
from test_daily_future_failure_continuity import unreachable_future
from test_daily_main_active_pipeline import with_mode
from test_daily_main_horizon_retention import recover

from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def test_restart_does_not_resume_stored_plan_without_fresh_planning(tmp_path):
    store, snapshot, _, _, _ = unreachable_future(tmp_path)
    calls = []
    restarted = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ha")),
        commitment_store=ActivePlanCommitmentStore(store._path),
    )
    outcome = restarted.advance_committed_boundary(snapshot, execution_enabled=True)
    assert outcome.status == "blocked"
    assert outcome.failure_reason == "daily_main_execution_awaits_valid_planning"
    assert not calls


def test_missing_data_recovery_expiry_restart_and_day_change(tmp_path):
    store, snapshot, conversion, completed, tomorrow = unreachable_future(tmp_path)
    original_plan = store.load_active_daily_main_plan("battery")
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ha")),
        commitment_store=store,
    )

    def plan(source):
        return CanonicalPipeline(commitment_store=store,
            market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion)).run(
                planning_input=source, control_change_allowed=True)

    missing = replace(snapshot, household_load_forecast=None)
    fallback = plan(missing)
    assert fallback.evaluation.status == "fallback_active"
    runtime.apply(fallback)
    assert runtime.advance_committed_boundary(snapshot, execution_enabled=True).status == "blocked"

    recovered = plan(snapshot)
    assert recovered.evaluation.status == "plan_retained"
    applied = runtime.apply_committed(recovered, snapshot)
    assert applied.vendor_result.status in {"dispatched", "already_active"}
    # The simulated HA boundary confirms the successful mode command.
    snapshot = with_mode(snapshot, applied.primitive_boundary.planned_primitive,
                         current_mode=applied.vendor_result.planned_vendor_mode)
    proof = recovered.evaluation.execution_continuity
    assert proof is not None
    # A pending day's start is a hard recheck boundary, even within 15 minutes.
    assert proof.valid_until <= tomorrow.starts_at
    before_deadline = snapshot
    store = ActivePlanCommitmentStore(store._path)
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ha")),
        commitment_store=store,
    )
    held = runtime.advance_committed_boundary(before_deadline, execution_enabled=True)
    assert held.status == "blocked"
    fresh_run = plan(recover(before_deadline, store))
    runtime.apply_committed(fresh_run, before_deadline)
    assert store.load_active_daily_main_plan("battery") == original_plan

    next_day = recover(observed_at(snapshot, tomorrow.starts_at), store)
    expired = runtime.advance_committed_boundary(next_day, execution_enabled=True)
    assert expired.failure_reason == "current_execution_proof_expired_or_replaced"
    day_run = plan(next_day)
    assert day_run.evaluation.status == "fallback_active"
    runtime.apply(day_run)
    assert runtime.advance_committed_boundary(next_day, execution_enabled=True).status == "blocked"

    # When physical feasibility returns, real Candidate/Evaluation restores execution.
    feasible = replace(next_day, storage_physical_limits=tuple(
        replace(limit, maximum_charge_input_power_w=2400)
        for limit in next_day.storage_physical_limits))
    restored = plan(feasible)
    assert restored.execution_record.status == "live_plan_ready", restored.evaluation.reason
    executed = runtime.apply_committed(restored, recover(feasible, store))
    assert executed.vendor_result.status in {"dispatched", "already_active"}
    assert next(a for a in store.load_daily_assignments()
                if a.assignment_id == completed.assignment_id) == completed
    assert next(a for a in store.load_daily_assignments()
                if a.assignment_id == tomorrow.assignment_id).completed_at is None


def test_restart_full_soc_can_complete_after_fresh_plan_admission(tmp_path, monkeypatch):
    from datetime import timedelta

    from test_daily_main_active_pipeline import setup

    store, pipeline, recover_input = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover_input())
    stored = store.load_active_daily_main_plan("battery")
    segment = next(s for s in stored.segments if s.main_assignment_id is not None)
    at = segment.starts_at + timedelta(seconds=1)
    measured = segment.starts_at - timedelta(minutes=10)
    source = replace(selected.planning_input, daily_charge_context=None, captured_at=at,
        capability_snapshot_set=replace(selected.planning_input.capability_snapshot_set,
                                         captured_at=at),
        current_storage_states=tuple(replace(state, current_soc=1,
            measured_at=measured, state_valid_since=measured, state_read_at=at)
            for state in selected.planning_input.current_storage_states))
    source = recover_input(with_mode(source, segment.primitive, current_mode="Test active"))
    commands = []
    runtime = CanonicalExecutionRuntime(lambda *args: commands.append(args), commitment_store=store)
    assert runtime.advance_committed_boundary(source, execution_enabled=True).status == "blocked"
    assert store.load_daily_assignments()[0].completed_at is None
    admitted = pipeline.run(planning_input=source, control_change_allowed=True)
    assert admitted.execution_record.status == "live_plan_ready", admitted.evaluation.reason
    result = runtime.apply_committed(admitted, source)
    assert result.vendor_result.status == "already_active"
    assert store.load_daily_assignments()[0].completed_at == at
    assert not commands
