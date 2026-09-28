"""Recovery is evidence for each complete alternative, not a portfolio veto."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import comparison, scenario
from test_market_revision_failed_goal import failed_main_scenario

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.evaluation import CandidateValidity
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.market_revision_candidates import market_revision_windows
from picot.planner.market_route_admission import MarketRecoverySegment, common_market_recovery
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.plan_commitment_store import _serialize_daily, _serialize_execution_plan


def repair_comparison(tmp_path):
    store, snapshot, _ = failed_main_scenario(tmp_path)
    today = next(a for a in snapshot.daily_charge_context.assignments
                 if a.completed_at is not None)
    today = replace(today, completed_at=None, completion_evidence_id=None,
                    completion_segment_id=None)
    payload = store._load_payload()
    payload["daily_assignments"][today.assignment_id] = _serialize_daily(today)
    store._write(payload)
    snapshot = replace(
        snapshot,
        household_load_forecast=replace(snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=40)
            for i in snapshot.household_load_forecast.intervals)),
        price_points=tuple(replace(p, value_eur_per_kwh=-0.5) if n in (32, 33) else p
                           for n, p in enumerate(snapshot.price_points)),
    )
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = next(t for t in adapter.main_route_shortfalls(
        snapshot=snapshot, conversion_model=conversion,
    ) if t.assignment_id == today.assignment_id)
    windows = market_revision_windows(snapshot=snapshot, trigger=trigger,
                                      conversion_model=conversion)
    basis = windows.market_revision
    incumbent = adapter.main_charge_incumbent(
        snapshot=snapshot, assignment=today, conversion_model=conversion,
        horizon_end=basis.horizon_end,
    )
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=basis.horizon_end)
    return snapshot, windows, incumbent, tariffs


def test_unproven_candidate_cannot_disable_good_candidates_or_change_their_winner(tmp_path):
    snapshot, windows, incumbent, tariffs = repair_comparison(tmp_path)
    basis = windows.market_revision
    recovery = tuple(MarketRecoverySegment(
        basis.recovery_assignment_id, start, end,
        snapshot.current_storage_states[0].usable_capacity_wh,
    ) for start, end in basis.recovery_intervals)

    def proven(window):
        return common_market_recovery(
            projections=(window.projection,), recovery_segments=recovery,
            after=max(end for _, end in basis.export_intervals),
        ) is not None

    good = tuple(w for w in windows.windows if proven(w))
    bad = tuple(w for w in windows.windows if not proven(w))
    assert good and bad and incumbent.invalidity_reasons
    winners = []
    reference = None
    for alternatives in (good, good + bad[:1], tuple(reversed(good + bad))):
        portfolio = produce_main_charge_portfolio(
            snapshot=snapshot, windows=replace(windows, windows=alternatives),
            tariffs=tariffs, opportunity_ids=(), incumbent=incumbent,
        )
        comparable = {e.candidate_id: e.comparable_result_eur
                      for e in portfolio.market_revision_evidence
                      if e.comparable_result_eur is not None}
        if reference is None:
            reference = comparable
        assert comparable == reference
        assert len(comparable) == len(good)
        assert all(e.delta_from_incumbent_eur is None
                   for e in portfolio.market_revision_evidence)
        for outcome in portfolio.outcome_set.outcomes:
            if outcome.candidate_id not in comparable:
                assert outcome.validity is CandidateValidity.INVALID
        selected = EvaluationEngine().evaluate(
            portfolio.candidate_set, portfolio.strategy, portfolio.outcome_set,
            created_at=snapshot.captured_at,
            incumbent_candidate_id=portfolio.incumbent_candidate_id,
        )
        winners.append(selected.record.winning_candidate_id)
    assert len(set(winners)) == 1


def test_canonical_capability_failure_cannot_supply_savings_reference(tmp_path):
    _, snapshot, _ = scenario(tmp_path, export_prices=(-0.5, -0.5))
    caps = snapshot.capability_snapshot_set
    snapshot = replace(snapshot, capability_snapshot_set=replace(
        caps, capabilities=tuple(replace(c, supported_primitives=tuple(
            p for p in c.supported_primitives if p is not ExecutionPrimitive.DISCHARGE_AT_POWER
        )) for c in caps.capabilities),
    ))
    _, portfolio, result = comparison(snapshot)
    incumbent = next(o for o in portfolio.outcome_set.outcomes
                     if o.candidate_id == portfolio.incumbent_candidate_id)
    assert incumbent.validity is CandidateValidity.INVALID
    assert "unsupported_primitive:discharge_at_power" in incumbent.invalidity_reasons
    winner = next(e for e in portfolio.market_revision_evidence
                  if e.candidate_id == result.record.winning_candidate_id)
    assert winner.variant == "removed"
    assert winner.comparable_result_eur is not None
    assert all(e.delta_from_incumbent_eur is None for e in portfolio.market_revision_evidence)


def test_full_goal_then_household_consumption_has_equal_real_recovery_stock(tmp_path):
    store, snapshot, plan = scenario(tmp_path, export_prices=(-0.5, -0.5))
    today, tomorrow = snapshot.daily_charge_context.assignments
    today = replace(today, completed_at=None, completion_evidence_id=None,
                    completion_segment_id=None)
    start, end = tomorrow.main_segments[0].starts_at, tomorrow.main_segments[-1].ends_at
    plan = replace(plan, segments=tuple(replace(
        s, primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL, requested_power_w=None,
        charge_source_policy=ChargeSourcePolicy.PV_ONLY,
    ) if s.main_assignment_id == tomorrow.assignment_id else s for s in plan.segments))
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in (today, tomorrow)},
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(plan)
                               for a in (today, tomorrow)},
        execution_plans={plan.plan_id: _serialize_execution_plan(plan)},
    )
    store._write(payload)
    snapshot = replace(
        snapshot,
        household_load_forecast=replace(snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=40)
            for i in snapshot.household_load_forecast.intervals)),
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, intervals=tuple(replace(
            i, pv_energy_wh=2000, forecast_lower_energy_wh=2000,
            forecast_central_energy_wh=2000, forecast_upper_energy_wh=2000,
        ) if start <= i.starts_at < end - timedelta(minutes=45) else i
            for i in snapshot.pv_energy_timeline.intervals)),
    )
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = next(t for t in adapter.main_route_shortfalls(
        snapshot=snapshot, conversion_model=conversion,
    ) if t.assignment_id == today.assignment_id)
    windows = market_revision_windows(snapshot=snapshot, trigger=trigger,
                                      conversion_model=conversion)
    incumbent = adapter.main_charge_incumbent(snapshot=snapshot, assignment=today,
        conversion_model=conversion, horizon_end=windows.market_revision.horizon_end)
    assert incumbent.invalidity_reasons
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.market_revision.horizon_end,
    )
    reference = None
    for alternatives in (windows.windows, tuple(reversed(windows.windows))):
        portfolio = produce_main_charge_portfolio(snapshot=snapshot,
            windows=replace(windows, windows=alternatives), tariffs=tariffs,
            opportunity_ids=(), incumbent=incumbent)
        evidence = tuple(e for e in portfolio.market_revision_evidence
                         if e.comparable_result_eur is not None)
        assert len(evidence) == len(windows.windows) > 1
        assert all(e.terminal_storage_wh == pytest.approx(8040) for e in evidence)
        assert all(e.delta_from_incumbent_eur is None for e in evidence)
        values = {e.candidate_id: e.comparable_result_eur for e in evidence}
        if reference is None:
            reference = values
        assert values == reference
