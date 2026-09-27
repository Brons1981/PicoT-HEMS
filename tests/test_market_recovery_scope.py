"""Each market decision owns its recovery, not another day's later export."""

from dataclasses import asdict, replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from test_daily_main_charge_windows import inputs as physical_inputs
from test_market_revision_comparison import scenario
from test_market_route_admission import inputs as admission_inputs

from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.planner.market_route_admission import assess_market_route
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import _serialize_daily, _serialize_execution_plan


def test_automatic_trade_waits_for_recovery_even_when_legacy_option_is_off():
    args = admission_inputs(recovery=False)
    args.update(tariffs=None, recovery_segments=())
    result = assess_market_route(**args)
    assert result.status == "insufficient_evidence"
    assert result.incremental_net_profit_eur is None


def test_automatic_trade_rejects_a_spread_that_loses_money_on_actual_recovery():
    args = admission_inputs(recovery=False)
    tariffs = args["tariffs"]
    args["tariffs"] = replace(tariffs, intervals=tuple(
        replace(p, import_eur_per_kwh=1.0) if n == 1 else p
        for n, p in enumerate(tariffs.intervals)
    ))
    result = assess_market_route(**args)
    assert result.status == "rejected"
    assert result.incremental_net_profit_eur < 0


def future_trade_case(tmp_path):
    store, snapshot, old = scenario(tmp_path)
    context = snapshot.daily_charge_context
    binding = context.market_plan_bindings[0]
    trade = next(s for s in old.segments if s.segment_id in binding.segment_ids)
    start, end = trade.starts_at + timedelta(days=1), trade.ends_at + timedelta(days=1)
    old_market = store.load_market_daily_assignments()[0]
    market = MarketDailyAssignment(
        old_market.rule, old_market.execution_scope_id,
        old_market.delivery_date + timedelta(days=1), old_market.timezone,
        old_market.created_at, old_market.usable_capacity_wh,
    )
    segments = []
    for part in old.segments:
        if part == trade:
            segments.append(replace(part, primitive=Primitive.BALANCE_DISCHARGE_ONLY,
                                    purpose="retained-route", requested_power_w=None))
        elif part.starts_at <= start < end <= part.ends_at:
            segments.extend((
                replace(part, segment_id="before-next-trade", ends_at=start),
                replace(trade, segment_id="next-trade", starts_at=start, ends_at=end,
                        purpose=market.assignment_id),
                replace(part, segment_id="after-next-trade", starts_at=end),
            ))
        else:
            segments.append(part)
    plan = replace(old, segments=tuple(replace(s, order=n + 1)
                                      for n, s in enumerate(segments)))
    # Today's old charge did not actually complete. Tomorrow has a retained
    # four-hour charge before its own export. Repair today may not revise that trade.
    owners = tuple(replace(a, completed_at=None, completion_evidence_id=None,
                           completion_segment_id=None) for a in context.assignments)
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in owners},
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(plan) for a in owners},
        execution_plans={plan.plan_id: _serialize_execution_plan(plan)},
        market_daily_assignments={market.assignment_id: store._market_assignment_payload(market)},
        market_plan_bindings={market.assignment_id: asdict(replace(
            binding, assignment_id=market.assignment_id, segment_ids=("next-trade",)))},
    )
    store._write(payload)
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    assert snapshot.daily_charge_context.status == "ready"
    return store, snapshot, plan, market


def test_today_repair_cannot_reconsider_tomorrows_post_charge_market(tmp_path):
    store, snapshot, old, market = future_trade_case(tmp_path)
    result = CanonicalPipeline(
        commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(
            physical_inputs()["conversion_model"]),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    assert result.outcomes.market_revision_evidence == ()
    active = store.load_active_daily_main_plan("battery")
    fields = ("starts_at", "ends_at", "primitive", "requested_power_w", "soc_constraint")
    before = [tuple(getattr(s, f) for f in fields) for s in old.segments
              if s.purpose == market.assignment_id]
    after = [tuple(getattr(s, f) for f in fields) for s in active.segments
             if s.purpose == market.assignment_id]
    assert after[0][0] == before[0][0] and after[-1][1] == before[-1][1]
    assert all(a[1] == b[0] for a, b in zip(after, after[1:], strict=False))
    assert all(any(old[0] <= part[0] < part[1] <= old[1] and part[2:] == old[2:]
                   for old in before) for part in after)
    assert sum(store.load_market_plan_bindings()[0].segment_export_wh) == 1000
