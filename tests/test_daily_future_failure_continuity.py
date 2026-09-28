"""A future unsolved daily goal is distinct from the current admitted execution."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import with_mode
from test_daily_main_charge_windows import dev243_snapshot_and_conversion
from test_daily_main_horizon_retention import recover, select
from test_daily_main_route_optimisation import fresh

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def unreachable_future(tmp_path):
    original, conversion = dev243_snapshot_and_conversion()
    original = replace(
        original,
        capability_snapshot_set=replace(
            original.capability_snapshot_set,
            capabilities=tuple(replace(c, supported_primitives=(
                Primitive.BALANCE_BIDIRECTIONAL, Primitive.BALANCE_DISCHARGE_ONLY,
                Primitive.CHARGE_AT_POWER,
            )) for c in original.capability_snapshot_set.capabilities),
        ),
    )
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    source = recover(original, store)
    today, tomorrow = source.daily_charge_context.assignments
    window, plans, _ = select(source, today, conversion)
    saved = store.bind_daily_main_plan(plan=plans.plans[0], window=window, activate=True)
    part = saved.main_segments[-1]
    measured = part.ends_at - timedelta(seconds=1)
    completed = store.observe_daily_main_completion(
        execution_scope_id="battery", plan_id=saved.route_plan_id, segment_id=part.segment_id,
        confirmed_since=part.starts_at, observed_at=measured, measured_at=measured,
        soc=1.0, evidence_id="observed-full",
    )
    at = part.ends_at + timedelta(seconds=5)
    candidate = fresh(source, pv_factor=0.0, soc=0.8, tag="future-goal-unreachable")
    candidate = replace(
        candidate, captured_at=at,
        current_storage_states=tuple(replace(s, measured_at=at)
                                     for s in candidate.current_storage_states),
        capability_snapshot_set=replace(candidate.capability_snapshot_set, captured_at=at),
        storage_physical_limits=tuple(replace(lim, maximum_charge_input_power_w=1.0)
                                      for lim in candidate.storage_physical_limits),
    )
    candidate = recover(with_mode(candidate, Primitive.BALANCE_DISCHARGE_ONLY), store)
    return store, candidate, conversion, completed, tomorrow


def run_pipeline(store, snapshot, conversion):
    return CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion),
        commitment_store=store,
    ).run(planning_input=snapshot)


def test_future_unreachable_goal_preserves_only_current_proven_execution(tmp_path):
    store, snapshot, conversion, completed, tomorrow = unreachable_future(tmp_path)
    active = store.load_active_daily_main_plan("battery")
    due = next(s for s in active.segments if s.starts_at <= snapshot.captured_at < s.ends_at)
    assert due.primitive is Primitive.BALANCE_DISCHARGE_ONLY
    assert tomorrow.starts_at > snapshot.captured_at
    assert IndependentDailyReferenceAdapter().main_route_shortfalls(
        snapshot=snapshot, conversion_model=conversion,
    ) == ()
    before = (tmp_path / "plans.json").read_bytes()
    run = run_pipeline(store, snapshot, conversion)
    assert run.evaluation.status == "plan_retained"
    assert run.evaluation.reason.startswith("future_daily_goal_unresolved:")
    assert tomorrow.assignment_id in run.evaluation.reason
    assert run.primitive_boundary.planned_primitive is due.primitive
    assert run.execution_record.status == "observer_only_plan_ready"
    assert run.evaluation.winning_candidate_id is None
    assert run.evaluation.canonical_record is None
    assert (tmp_path / "plans.json").read_bytes() == before
    today, pending = store.load_daily_assignments()
    assert today == completed
    assert pending.assignment_id == tomorrow.assignment_id
    assert pending.route_plan_id is None and pending.completed_at is None

    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    observed = recover(snapshot, restarted)
    repeated = run_pipeline(restarted, observed, conversion)
    assert repeated.primitive_boundary.planned_primitive is due.primitive
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ok")
        ),
        commitment_store=restarted,
    )
    outcome = runtime.advance_committed_boundary(observed, execution_enabled=True)
    assert outcome.status == "dispatched"
    assert calls[0].primitive is due.primitive
    assert calls[0].segment_id == due.segment_id
    assert restarted.load_active_daily_main_plan("battery") == active


@pytest.mark.parametrize("missing", ["pv_energy_timeline", "household_load_forecast"])
def test_future_failure_never_hides_missing_current_inputs(tmp_path, missing):
    store, snapshot, conversion, _, _ = unreachable_future(tmp_path)
    before = (tmp_path / "plans.json").read_bytes()
    run = run_pipeline(store, replace(snapshot, **{missing: None}), conversion)
    assert run.execution_record.status == "observer_fallback_ready"
    assert run.evaluation.status == "fallback_active"
    assert run.primitive_boundary.planned_primitive is Primitive.BALANCE_BIDIRECTIONAL
    assert (tmp_path / "plans.json").read_bytes() == before


@pytest.mark.parametrize("invalid", ["reserve", "capability", "goal_due"])
def test_future_failure_does_not_approve_invalid_current_execution(tmp_path, invalid):
    store, snapshot, conversion, _, tomorrow = unreachable_future(tmp_path)
    if invalid == "reserve":
        snapshot = replace(snapshot, current_storage_states=tuple(
            replace(s, current_soc=0.05) for s in snapshot.current_storage_states
        ))
    elif invalid == "capability":
        snapshot = replace(snapshot, capability_snapshot_set=replace(
            snapshot.capability_snapshot_set, capabilities=tuple(
                replace(c, supported_primitives=(Primitive.BALANCE_BIDIRECTIONAL,))
                for c in snapshot.capability_snapshot_set.capabilities
            ),
        ))
    else:
        at = tomorrow.starts_at + timedelta(seconds=1)
        snapshot = replace(
            snapshot, captured_at=at, daily_charge_context=None,
            current_storage_states=tuple(replace(s, measured_at=at)
                                         for s in snapshot.current_storage_states),
            capability_snapshot_set=replace(snapshot.capability_snapshot_set, captured_at=at),
            storage_mode_capability_evidence=replace(
                snapshot.storage_mode_capability_evidence, captured_at=at,
            ),
        )
        snapshot = recover(snapshot, store)
    before = (tmp_path / "plans.json").read_bytes()
    run = run_pipeline(store, snapshot, conversion)
    assert run.execution_record.status == "observer_fallback_ready"
    assert run.evaluation.status == "fallback_active"
    assert (tmp_path / "plans.json").read_bytes() == before
