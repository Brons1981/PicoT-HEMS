from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_charge_windows import inputs
from test_independent_daily_reference_adapter import _snapshot

from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.evaluation import EvaluationOutcomeStatus
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.objectives import ObjectiveKind
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def snapshot_for_main():
    snapshot = _snapshot()
    caps = snapshot.capability_snapshot_set
    return replace(
        snapshot,
        capability_snapshot_set=replace(
            caps,
            capabilities=tuple(
                replace(
                    c,
                    supported_primitives=(
                        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                        ExecutionPrimitive.CHARGE_AT_POWER,
                    ),
                )
                for c in caps.capabilities
            ),
        ),
    )


def portfolio_fixture():
    snapshot = snapshot_for_main()
    a = DailyChargeAssignment("battery", snapshot.captured_at.date(), "UTC", snapshot.captured_at)
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=a, conversion_model=inputs()["conversion_model"]
    )
    # A short cheap window at the beginning, expensive later. Independent known
    # prices; no test copy of the settlement or ranking algorithm.
    intervals = windows.windows[0].projection.intervals
    tariffs = DailyReferenceTariffSchedule(
        schedule_id="prices",
        snapshot_id=snapshot.snapshot_id,
        horizon_start=intervals[0].starts_at,
        horizon_end=intervals[-1].ends_at,
        intervals=tuple(
            DailyReferenceTariffInterval(
                i.starts_at,
                i.ends_at,
                0.1 if i.starts_at < snapshot.captured_at + timedelta(hours=3) else 0.5,
                0.05,
                1,
                ("price-evidence",),
            )
            for i in intervals
        ),
        method_version="test:v1",
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=("published-prices",)
    )
    return snapshot, a, windows, tariffs, portfolio


def evaluate(snapshot, portfolio):
    return EvaluationEngine().evaluate(
        portfolio.candidate_set,
        portfolio.strategy,
        portfolio.outcome_set,
        created_at=snapshot.captured_at,
    )


def test_canonical_evaluation_selects_lowest_effective_charge_price():
    snapshot, _, windows, _, portfolio = portfolio_fixture()
    result = evaluate(snapshot, portfolio)
    assert result.status is EvaluationOutcomeStatus.WINNER_SELECTED
    selected = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    assert selected.financial.acquisition_eur_per_stored_kwh == min(
        s.financial.acquisition_eur_per_stored_kwh for s in portfolio.sources
    )
    assert result.record.decisive_step is not None
    assert len(portfolio.candidate_set.candidates) == len(windows.windows)
    assert selected.window.main_segments[0].starts_at < snapshot.captured_at + timedelta(hours=3)
    assert ObjectiveKind.FINANCIAL_RESULT in result.record.strategic_objective_order


def test_cash_result_does_not_add_avoided_import_twice():
    _, _, windows, tariffs, _ = portfolio_fixture()
    projection = windows.windows[0].projection
    result = IndependentDailyFinancialSettlement().settle_planning_basis(
        projection=projection, tariffs=tariffs
    )
    # Cash has only import/export. These tariffs have no fiscal offsets, so
    # expected cash can be checked directly from conserved physical flows.
    expected = sum(
        (
            (p.pv_to_grid_wh + p.storage_to_grid_output_wh) * t.export_eur_per_kwh
            - (p.grid_to_household_wh + p.grid_to_storage_input_wh) * t.import_eur_per_kwh
        )
        / 1000
        for p, t in zip(projection.intervals, tariffs.intervals, strict=True)
    )
    assert result.cash_result_eur == pytest.approx(expected)
    assert sum(i.avoided_import_value_eur for i in result.intervals) > 0
    assert sum(i.net_financial_result_eur for i in result.intervals) > result.cash_result_eur


def test_selected_path_builder_and_store_preserve_main_ownership(tmp_path):
    snapshot, a, _, _, portfolio = portfolio_fixture()
    result = evaluate(snapshot, portfolio)
    selected = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    plan_set = ExecutionPlanBuilder().build(
        result, created_at=snapshot.captured_at, fallback_policy_id="nom-fallback"
    )
    (plan,) = plan_set.plans
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(a)
    bound = store.bind_daily_main_plan(plan=plan, window=selected.window)
    assert bound.assignment_id == a.assignment_id
    assert bound.route_plan_id == plan.plan_id
    assert bound.revision_evidence_id == result.record.evaluation_id
    assert bound.completed_at is None  # projected 100% is never observed completion
    assert set(s.segment_id for s in bound.main_segments) == {
        s.segment_id
        for s in plan.segments
        if s.source_path_segment_id in {m.segment_id for m in selected.window.main_segments}
    }
    (loaded,) = ActivePlanCommitmentStore(tmp_path / "plans.json").load_daily_assignments()
    assert loaded == bound
    assert store.bind_daily_main_plan(plan=plan, window=selected.window) == bound
    path = result.winning_energy_path
    assert (
        path.projected_states[-1].storage_energy_wh
        == selected.window.projection.intervals[-1].storage_energy_at_end_wh
    )
    assert any(s.household_import_w > 0 for s in path.projected_states[1:])


def test_unsupported_charge_primitive_cannot_become_a_winner():
    snapshot, _, windows, tariffs, _ = portfolio_fixture()
    caps = snapshot.capability_snapshot_set
    snapshot = replace(
        snapshot,
        capability_snapshot_set=replace(
            caps,
            capabilities=tuple(
                replace(c, supported_primitives=(ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,))
                for c in caps.capabilities
            ),
        ),
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=("prices",)
    )
    result = evaluate(snapshot, portfolio)
    assert result.status is EvaluationOutcomeStatus.NO_VALID_CANDIDATE
    assert result.record.invalid_candidates


def test_cross_snapshot_settlement_is_rejected():
    _, _, windows, tariffs, _ = portfolio_fixture()
    with pytest.raises(ValueError, match="snapshots must match"):
        IndependentDailyFinancialSettlement().settle_planning_basis(
            projection=windows.windows[0].projection, tariffs=replace(tariffs, snapshot_id="other")
        )


def test_wrong_window_and_changed_main_boundaries_cannot_be_bound(tmp_path):
    snapshot, a, _, _, portfolio = portfolio_fixture()
    result = evaluate(snapshot, portfolio)
    selected = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    (plan,) = (
        ExecutionPlanBuilder()
        .build(result, created_at=snapshot.captured_at, fallback_policy_id="nom")
        .plans
    )
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(a)
    other = next(s for s in portfolio.sources if s.candidate_id != selected.candidate_id)
    with pytest.raises(ValueError, match="explicit main source segment"):
        store.bind_daily_main_plan(plan=plan, window=other.window)
    owned = {s.segment_id for s in selected.window.main_segments}
    changed = replace(
        plan,
        segments=tuple(
            replace(s, ends_at=s.ends_at - timedelta(seconds=1))
            if s.source_path_segment_id in owned
            else s
            for s in plan.segments
        ),
    )
    with pytest.raises(ValueError, match="boundaries"):
        store.bind_daily_main_plan(plan=changed, window=selected.window)
    assert store.load_daily_assignments() == (a,)


def test_new_selection_cannot_replace_a_bound_main_route_without_trigger(tmp_path):
    snapshot, a, _, _, portfolio = portfolio_fixture()
    result = evaluate(snapshot, portfolio)
    selected = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    (plan,) = (
        ExecutionPlanBuilder()
        .build(result, created_at=snapshot.captured_at, fallback_policy_id="nom")
        .plans
    )
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(a)
    bound = store.bind_daily_main_plan(plan=plan, window=selected.window)
    with pytest.raises(ValueError, match="optimisation trigger"):
        store.bind_daily_main_plan(
            plan=replace(plan, plan_id="competing-plan"), window=selected.window
        )
    assert store.load_daily_assignments() == (bound,)


def test_dev243_evaluation_and_plan_builder_choose_midday_grid_charge(tmp_path):
    from datetime import date
    from zoneinfo import ZoneInfo

    from test_daily_main_charge_windows import dev243_snapshot_and_conversion

    from picot.domain.daily_reference_intent import DailyStorageIntent
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

    snapshot, conversion = dev243_snapshot_and_conversion()
    caps = snapshot.capability_snapshot_set
    snapshot = replace(
        snapshot,
        capability_snapshot_set=replace(
            caps,
            capabilities=tuple(
                replace(
                    c,
                    supported_primitives=(
                        ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                        ExecutionPrimitive.CHARGE_AT_POWER,
                    ),
                )
                for c in caps.capabilities
            ),
        ),
    )
    a = DailyChargeAssignment("battery", date(2026, 9, 8), "Europe/Amsterdam", snapshot.captured_at)
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=a, conversion_model=conversion
    )
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.windows[0].schedule.horizon_end
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=("published-prices",)
    )
    result = evaluate(snapshot, portfolio)
    selected = next(
        s for s in portfolio.sources if s.candidate_id == result.record.winning_candidate_id
    )
    grid = tuple(
        s for s in selected.window.main_segments if s.intent is DailyStorageIntent.GRID_REQUIREMENT
    )
    assert grid
    assert all(11 <= s.starts_at.astimezone(ZoneInfo("Europe/Amsterdam")).hour < 15 for s in grid)
    (plan,) = (
        ExecutionPlanBuilder()
        .build(result, created_at=snapshot.captured_at, fallback_policy_id="nom")
        .plans
    )
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    store.save_daily_assignment(a)
    bound = store.bind_daily_main_plan(plan=plan, window=selected.window)
    assert bound.route_plan_id == plan.plan_id
    assert bound.completed_at is None
    assert selected.financial.acquisition_eur_per_stored_kwh == min(
        s.financial.acquisition_eur_per_stored_kwh for s in portfolio.sources
    )


@pytest.mark.parametrize(
    "intent,pv,expected",
    [
        ("grid_requirement", 0, 0.25),
        ("nom", 1000, 0.125),
        ("grid_requirement", 200, 0.23 / 0.96),
    ],
)
def test_main_acquisition_price_counts_household_and_losses_correctly(intent, pv, expected):
    from test_independent_daily_intent_simulator import _schedule

    from picot.domain.daily_reference_intent import DailyStorageIntent
    from picot.planner.independent_daily_intent_simulator import IndependentDailyIntentSimulator

    data = inputs(lower=pv, central=pv)
    data["conversion_model"] = replace(data["conversion_model"], charge_efficiency=0.8)
    projection = IndependentDailyIntentSimulator().simulate_planning_basis(
        **data, intent_schedule=_schedule(DailyStorageIntent(intent))
    )
    tariffs = DailyReferenceTariffSchedule(
        schedule_id="constant",
        snapshot_id=projection.snapshot_id,
        horizon_start=projection.intervals[0].starts_at,
        horizon_end=projection.intervals[-1].ends_at,
        intervals=tuple(
            DailyReferenceTariffInterval(i.starts_at, i.ends_at, 0.2, 0.1, 1, ("price",))
            for i in projection.intervals
        ),
        method_version="test:v1",
    )
    first = projection.intervals[0]
    result = IndependentDailyFinancialSettlement().settle_planning_basis(
        projection=projection, tariffs=tariffs, main_intervals=((first.starts_at, first.ends_at),)
    )
    assert result.acquisition_eur_per_stored_kwh == pytest.approx(expected)
    assert result.acquisition_input_wh == pytest.approx(
        first.grid_to_storage_input_wh + first.pv_to_storage_input_wh
    )
    assert result.acquisition_stored_wh == pytest.approx(0.8 * result.acquisition_input_wh)


def test_already_full_has_no_invented_zero_unit_price():
    snapshot = snapshot_for_main()
    snapshot = replace(
        snapshot,
        current_storage_states=(replace(snapshot.current_storage_states[0], current_soc=1),),
    )
    a = DailyChargeAssignment("battery", snapshot.captured_at.date(), "UTC", snapshot.captured_at)
    windows = IndependentDailyReferenceAdapter().main_charge_windows(
        snapshot=snapshot, assignment=a, conversion_model=inputs()["conversion_model"]
    )
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.windows[0].schedule.horizon_end
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=("prices",)
    )
    assert portfolio.sources[0].financial.acquisition_eur_per_stored_kwh is None
    result = evaluate(snapshot, portfolio)
    assert result.status is EvaluationOutcomeStatus.WINNER_SELECTED
    assert not any(
        o.objective is ObjectiveKind.FINANCIAL_RESULT and o.available
        for o in result.record.objective_comparisons
    )
