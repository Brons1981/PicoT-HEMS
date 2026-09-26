"""ADR-019.5 with real simulation, settlement, Evaluation and publication.

The old admitted plan is an explicit fixture: today's charge has completed,
1000 Wh export is due at 18:00 UTC, tomorrow's main charge runs 02:00–06:00.
The 400 W household and equal terminal state make price effects inspectable.
"""

from dataclasses import asdict, replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_selection import snapshot_for_main
from test_daily_main_charge_windows import inputs

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import SocConstraint
from picot.domain.execution_plan import ExecutionPlan, ExecutionPlanLifecycle, ExecutionPlanSegment
from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.domain.market_user_rule import MarketUserRule
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.market_revision_candidates import market_revision_windows
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.daily_charge_assignment import (
    DailyChargeAssignment,
    DailyChargeRevisionReason,
    DailyChargeSegment,
)
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import (
    ActivePlanCommitmentStore,
    _serialize_daily,
    _serialize_execution_plan,
)


def scenario(tmp_path, export_prices=(0.8, 0.8), *, complete=True, soc=0.65):
    source = snapshot_for_main()
    at = source.captured_at
    end = at + timedelta(hours=36)
    quarter = timedelta(minutes=15)
    caps = replace(source.capability_snapshot_set, capabilities=tuple(
        replace(c, supported_primitives=tuple(Primitive))
        for c in source.capability_snapshot_set.capabilities))
    source = replace(
        source, horizon_end=end, capability_snapshot_set=caps,
        current_storage_states=tuple(replace(s, current_soc=soc)
                                     for s in source.current_storage_states),
        price_points=tuple(replace(source.price_points[0],
            point_id=f"p:{n}", starts_at=at + n * quarter, ends_at=at + (n + 1) * quarter,
            value_eur_per_kwh=export_prices[n - 32] if 32 <= n < 34 else
            0.05 if 56 <= n < 64 else 0.1,
        ) for n in range(144 if complete else 96)),
        household_load_forecast=replace(source.household_load_forecast, intervals=tuple(
            replace(source.household_load_forecast.intervals[0], interval_id=f"h:{n}",
                    starts_at=at + n * quarter, ends_at=at + (n + 1) * quarter,
                    expected_energy_wh=100)
            for n in range(144))),
        pv_energy_timeline=replace(source.pv_energy_timeline, intervals=tuple(
            replace(source.pv_energy_timeline.intervals[0], interval_id=f"pv:{n}",
                    starts_at=at + n * quarter, ends_at=at + (n + 1) * quarter,
                    pv_energy_wh=0, forecast_lower_energy_wh=0,
                    forecast_central_energy_wh=0, forecast_upper_energy_wh=0)
            for n in range(144))),
    )
    created = at - timedelta(hours=2)
    today = DailyChargeAssignment("battery", at.date(), "Europe/Amsterdam", created)
    tomorrow = DailyChargeAssignment("battery", at.date() + timedelta(days=1),
                                     "Europe/Amsterdam", created)
    market = MarketDailyAssignment(MarketUserRule("trade", 1, 0.25, 0), "battery", at.date(),
                                   "Europe/Amsterdam", created, 8160)
    boundaries = [created, at - timedelta(hours=1), at + timedelta(hours=8),
                  at + timedelta(hours=8, minutes=30), at + timedelta(hours=16),
                  at + timedelta(hours=20), end]
    parts = []
    for n, (start, stop) in enumerate(zip(boundaries, boundaries[1:], strict=False)):
        main = today if n == 0 else tomorrow if n == 4 else None
        primitive = (Primitive.CHARGE_AT_POWER if main else
                     Primitive.DISCHARGE_AT_POWER if n == 2 else Primitive.BALANCE_DISCHARGE_ONLY)
        parts.append(ExecutionPlanSegment(
            f"part:{n}", f"path-part:{n}", n + 1, start, stop, primitive,
            "battery-capability", market.assignment_id if n == 2 else
            f"main-charge:{main.assignment_id}" if main else "retained-route", ("old-plan",),
            requested_power_w=2400 if main or n == 2 else None,
            soc_constraint=SocConstraint(0.1, 1),
            charge_source_policy=ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED if main else None,
            main_assignment_id=main.assignment_id if main else None,
        ))
    plan = ExecutionPlan("old-plan", 1, 1, created, created, end, "old-snapshot", 1,
                         "old-evaluation", "old-candidate", "old-path", "battery", 1,
                         ExecutionPlanLifecycle.ACTIVE, "guarded-nom", tuple(parts))
    owners = []
    for owner, segment in ((today, parts[0]), (tomorrow, parts[4])):
        owners.append(replace(owner, route_plan_id=plan.plan_id,
            main_segments=(DailyChargeSegment(segment.segment_id,
                                              segment.starts_at, segment.ends_at),),
            revision=1, revised_at=created, revision_reason=DailyChargeRevisionReason.INITIAL,
            revision_evidence_id=plan.evaluation_id,
            completed_at=segment.ends_at if owner is today else None,
            completion_evidence_id="observed-full" if owner is today else None,
            completion_segment_id=segment.segment_id if owner is today else None))
    binding = MarketPlanBinding(market.assignment_id, "battery", plan.plan_id, plan.snapshot_id,
                                (parts[2].segment_id,), 1000, (1000,), 1200)
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.ensure_market_daily_assignment(market)
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in owners},
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(plan) for a in owners},
        execution_plans={plan.plan_id: _serialize_execution_plan(plan)},
        active_execution_plan_ids={"battery": plan.plan_id},
        active_daily_main_assignments={"battery": owners[0].assignment_id},
        market_plan_bindings={binding.assignment_id: asdict(binding)},
    )
    store._write(payload)
    snapshot = _restore_daily_charge_context(source, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    assert snapshot.daily_charge_context.status == "ready", snapshot.daily_charge_context.reason
    return store, snapshot, plan


def comparison(snapshot):
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    assert trigger is not None
    windows = market_revision_windows(snapshot=snapshot, trigger=trigger,
                                      conversion_model=conversion)
    end = windows.market_revision.horizon_end
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == windows.assignment_id)
    incumbent = adapter.main_charge_incumbent(snapshot=snapshot, assignment=owner,
                                              conversion_model=conversion, horizon_end=end)
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows,
        tariffs=IndependentDailyTariffAdapter().build(snapshot, horizon_end=end),
        opportunity_ids=("prices",), incumbent=incumbent,
    )
    result = EvaluationEngine().evaluate(portfolio.candidate_set, portfolio.strategy,
        portfolio.outcome_set, created_at=snapshot.captured_at,
        incumbent_candidate_id=portfolio.incumbent_candidate_id)
    return windows, portfolio, result


@pytest.mark.parametrize("prices,expected", [((0.8, 0.8), "retained"),
                                             ((-0.5, -0.5), "removed"),
                                             ((-0.5, 0.8), "shortened"),
                                             ((0.8, -0.5), "shortened")])
def test_joint_financial_comparison_can_keep_shorten_or_remove(tmp_path, prices, expected):
    _, snapshot, _ = scenario(tmp_path, prices)
    windows, portfolio, result = comparison(snapshot)
    evidence = portfolio.market_revision_evidence
    assert {e.variant for e in evidence} == {"retained", "shortened", "removed"}
    winner = next(e for e in evidence if e.candidate_id == result.record.winning_candidate_id)
    assert winner.variant == expected
    assert not winner.invalidity_reasons
    assert winner.horizon_end == windows.market_revision.required_horizon_end
    assert len(winner.days) == 2
    assert winner.terminal_storage_wh == pytest.approx(1760)
    assert winner.comparable_result_eur == pytest.approx(sum(
        day.export_revenue_eur - day.import_cost_eur for day in winner.days) - winner.wear_cost_eur)
    assert any(e.variant == "retained" and e.grid_charge_wh > 9600
               for e in evidence)


def test_incomplete_tomorrow_prices_allow_charge_repair_but_keep_export(tmp_path):
    _, snapshot, _ = scenario(tmp_path, complete=False)
    _, portfolio, result = comparison(snapshot)
    selected = next(e for e in portfolio.market_revision_evidence
                    if e.candidate_id == result.record.winning_candidate_id)
    assert selected.variant == "retained"
    assert selected.comparable_result_eur is None
    assert any("market_revision_today_tomorrow_coverage_incomplete" in e.invalidity_reasons
               for e in portfolio.market_revision_evidence if e.variant == "removed")


@pytest.mark.parametrize("prices,expected", [((0.8, 0.8), "pending"),
                                             ((-0.5, -0.5), "skipped"),
                                             ((0.8, -0.5), "pending")])
def test_real_pipeline_publishes_selected_revision_and_preserves_goals(tmp_path, prices, expected):
    store, snapshot, old_plan = scenario(tmp_path, prices)
    completed = next(a for a in store.load_daily_assignments() if a.completed_at is not None)
    pipeline = CanonicalPipeline(commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]))
    run = pipeline.run(planning_input=snapshot, control_change_allowed=False)
    assert run.evaluation.status in {"winner_selected", "plan_retained"}, run.evaluation.reason
    assert store.load_market_daily_assignments()[0].status == expected
    assert next(a for a in store.load_daily_assignments()
                if a.completed_at is not None) == completed
    active = store.load_active_daily_main_plan("battery")
    assert active is not None
    if run.evaluation.status == "winner_selected":
        assert active.winning_candidate_id == run.evaluation.winning_candidate_id
    else:
        assert active == old_plan
    restarted = ActivePlanCommitmentStore(tmp_path / "plans.json")
    assert restarted.load_active_daily_main_plan("battery") == active
