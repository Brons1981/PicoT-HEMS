"""An old trade's settlement cannot replace a newly admitted non-export action."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_active_pipeline import with_mode
from test_daily_main_charge_windows import inputs
from test_market_plan_revision import selected_revision

from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.daily_bridge import energy_deficits
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_plan_revision import build_market_plan_revisions
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.zendure_mode_capabilities import ZendureModeMapping


def replacement(tmp_path, monkeypatch, intent, begun):
    store, snapshot, _, old, args = selected_revision(
        tmp_path, monkeypatch, change="remove", begun=begun,
    )
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = args["optimisation_trigger"]
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion,
    )
    old_plan = store.load_market_bound_plan(old.assignment_id)
    trade = next(s for s in old_plan.segments if s.segment_id in old.segment_ids)
    schedule = replace(
        args["window"].schedule, schedule_id="replacement:" + intent.value,
        intervals=tuple(
            replace(i, intent=intent, storage_export_target_wh=0)
            if trade.starts_at <= i.starts_at < trade.ends_at else i
            for i in args["window"].schedule.intervals
        ),
    )
    projection = adapter._bridge_projection(
        snapshot, adapter._inputs(snapshot, horizon_end=schedule.horizon_end), schedule, conversion,
    )
    window = replace(args["window"], schedule=schedule, projection=projection)
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=replace(windows, windows=(window,)),
        tariffs=IndependentDailyTariffAdapter().build(snapshot, horizon_end=schedule.horizon_end),
        opportunity_ids=(),
    )
    evaluation = EvaluationEngine().evaluate(
        portfolio.candidate_set, portfolio.strategy, portfolio.outcome_set,
        created_at=snapshot.captured_at,
    )
    assert evaluation.winning_candidate is not None, evaluation.record.invalid_candidates
    plan = ExecutionPlanBuilder().build(
        evaluation, created_at=snapshot.captured_at, fallback_policy_id="guarded-nom",
    ).plans[0]
    revisions = build_market_plan_revisions(
        snapshot=snapshot, plan=plan, window=window, evaluation_record=evaluation.record,
    )
    store.bind_daily_main_plan(
        plan=plan, window=window, activate=True, optimisation_trigger=trigger,
        market_revisions=revisions,
        bridge_deficits=energy_deficits(
            projection, schedule, until=trigger.next_starts_at,
            maximum_discharge_output_power_w=2400,
        ),
    )
    return store, snapshot, old, plan


def observation(snapshot, store, at, current_mode):
    observed = with_mode(snapshot, Primitive.BALANCE_DISCHARGE_ONLY, current_mode=current_mode)
    observed = replace(
        observed, captured_at=at, daily_charge_context=None, market_power_history=None,
        capability_snapshot_set=replace(observed.capability_snapshot_set, captured_at=at),
        current_storage_states=tuple(replace(s, measured_at=at)
                                     for s in observed.current_storage_states),
        storage_mode_capability_evidence=replace(
            observed.storage_mode_capability_evidence, captured_at=at,
            state_changed_at=snapshot.captured_at,
            mappings=tuple(ZendureModeMapping(mode, (primitive,), "integration_configured_maximum")
                           for mode, primitive in (
                               ("Export", Primitive.DISCHARGE_AT_POWER),
                               ("Support", Primitive.BALANCE_DISCHARGE_ONLY),
                               ("Charge", Primitive.CHARGE_AT_POWER),
                               ("NOM", Primitive.BALANCE_BIDIRECTIONAL),
                           )),
        ),
    )
    return _restore_daily_charge_context(observed, store, local_timezone=ZoneInfo("UTC"))


@pytest.mark.parametrize("begun", [False, True])
@pytest.mark.parametrize("current_mode", ["NOM", "Export"])
@pytest.mark.parametrize("intent,primitive,mode", [
    (Intent.HOUSEHOLD_SUPPORT_ONLY, Primitive.BALANCE_DISCHARGE_ONLY, "Support"),
    (Intent.GRID_REQUIREMENT, Primitive.CHARGE_AT_POWER, "Charge"),
])
def test_selected_replacement_survives_old_settlement_and_restart(
    tmp_path, monkeypatch, begun, current_mode, intent, primitive, mode,
):
    store, snapshot, old, plan = replacement(tmp_path, monkeypatch, intent, begun)
    due = next(s for s in plan.segments
               if s.starts_at <= snapshot.captured_at < s.ends_at)
    assert due.primitive is primitive
    assert store.load_market_daily_assignments()[0].status == "pending"
    prior_measurement = store.load_market_progress(old.assignment_id).measured_export_wh
    calls = []
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: (
            calls.append(request) or CanonicalDispatchOutcome("dispatched", "ok")
        ),
        commitment_store=store,
    )
    result = runtime.advance_committed_boundary(
        observation(snapshot, store, snapshot.captured_at, current_mode), execution_enabled=True,
    )
    assert result.status == "dispatched"
    assert result.primitive is primitive
    assert calls[0].primitive is primitive
    assert calls[0].segment_id == due.segment_id
    assert store.load_active_daily_main_plan("battery") == plan
    progress = store.load_market_progress(old.assignment_id)
    assert progress.measured_export_wh == (prior_measurement if current_mode == "Export" else None)
    assert store.load_market_daily_assignments()[0].status == (
        "pending" if begun or current_mode == "Export" else "skipped"
    )

    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    runtime = CanonicalExecutionRuntime(
        lambda request, mapping: pytest.fail("confirmed replacement needs no repeated command"),
        commitment_store=restarted,
    )
    result = runtime.advance_committed_boundary(
        observation(snapshot, restarted, snapshot.captured_at + timedelta(minutes=10), mode),
        execution_enabled=True,
    )
    assert result.status == "already_active"
    assert result.primitive is primitive
    assert restarted.load_active_daily_main_plan("battery") == plan
    assert restarted.load_market_progress(old.assignment_id).measured_export_wh is None
