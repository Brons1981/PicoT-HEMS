"""In-memory canonical proof for an explicit joint EV/battery choice."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.evaluation import (
    CandidateOutcomeSet,
    ComparisonDirection,
    EvaluationResult,
    ObjectiveOutcome,
)
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.objectives import ObjectiveKind
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.execution_plan_builder import ExecutionPlanBuilder
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_recalculation import (
    DailyMainRecalculationTrigger,
    DailyPlanRecalculationRequest,
)
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter


@dataclass(frozen=True, slots=True)
class JointEVSelection:
    snapshot: PlanningInputSnapshot
    request: dict[str, Any]
    retained_plan_id: str
    plan: ExecutionPlan
    window: DailyMainChargeWindow | None = None
    trigger: DailyMainRecalculationTrigger | None = None
    evaluation: EvaluationResult | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    selection_id: str = ""
    terminal_storage_requirement_wh: float = 0.0


def rebuilt_selection(
    snapshot: PlanningInputSnapshot,
    request: dict[str, Any],
    retained: ExecutionPlan,
    conversion: StorageConversionModel,
    terminal_wh: float,
    *,
    equivalent_cache: dict[str, JointEVSelection | None] | None = None,
) -> JointEVSelection | None:
    """Use ordinary discovery and validity, with a common terminal reserve.

    An explicit EV request permits rebuilding the open daily route. It does not
    invent a shortage, release another day's owner, or change market obligations.
    """
    context = snapshot.daily_charge_context
    assert context is not None
    owners = sorted(
        (
            a
            for a in context.assignments
            if a.execution_scope_id == retained.execution_scope_id
            and a.completed_at is None
            and a.route_plan_id is not None
            and a.ends_at > snapshot.captured_at
        ),
        key=lambda a: a.ends_at,
    )
    if not owners:
        return None
    owner = owners[0]
    assert owner.route_plan_id is not None
    trigger = DailyMainRecalculationTrigger(
        owner.assignment_id,
        owner.route_plan_id,
        owner.revision,
        retained.plan_id,
        snapshot.snapshot_id,
        snapshot.captured_at,
        snapshot.current_storage_states[0].usable_capacity_wh,
        DailyPlanRecalculationRequest(
            f"ev:{request['session_id']}:{request['request_revision']}",
            snapshot.captured_at,
            (owner.assignment_id,),
        ),
    )
    adapter = IndependentDailyReferenceAdapter()
    forecast = snapshot.household_load_forecast
    pv = snapshot.pv_energy_timeline
    export_overlap = forecast is not None and any(
        load.battery_excluded_energy_wh > 0
        and any(
            s.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
            and s.starts_at < load.ends_at
            and load.starts_at < s.ends_at
            for s in retained.segments
        )
        for load in forecast.intervals
    )
    if export_overlap:
        # Existing market volumes are immutable in this main-route revision.
        # The canonical simulator forbids storage export during excluded load;
        # rebuilding a daily charge cannot resolve that export contradiction.
        return None
    cacheable = (
        equivalent_cache is not None
        and forecast is not None
        and pv is not None
        and all(
            all(
                v in (None, 0)
                for v in (
                    p.pv_energy_wh,
                    p.forecast_lower_energy_wh,
                    p.forecast_central_energy_wh,
                    p.forecast_upper_energy_wh,
                )
            )
            for p in pv.intervals
        )
    )
    cache_key = "no-pv-no-export-overlap"
    reused = False
    if cacheable:
        assert equivalent_cache is not None
    if cacheable and equivalent_cache is not None and cache_key in equivalent_cache:
        cached = equivalent_cache[cache_key]
        if cached is None:
            return None
        reused = True
        assert cached.window is not None
        physical = adapter._inputs(
            snapshot, horizon_end=retained.valid_until, maximum_duration=timedelta(hours=49)
        )
        projection = adapter._bridge_projection(
            snapshot, physical, cached.window.schedule, conversion
        )
        from picot.domain.daily_reference_charge_window import DailyMainChargeWindowSet

        windows = DailyMainChargeWindowSet(
            owner.assignment_id,
            snapshot.snapshot_id,
            (replace(cached.window, projection=projection),),
            "discovered",
            "equivalent_input",
            1,
        )
    else:
        windows = adapter.main_charge_windows(
            snapshot=replace(snapshot, horizon_end=retained.valid_until),
            assignment=owner,
            conversion_model=conversion,
            optimisation_trigger=trigger,
        )
    # Extra stock is unvalued; every route must meet the same end reserve.
    comparable_windows = tuple(
        w
        for w in windows.windows
        if w.schedule.horizon_end == retained.valid_until
        and w.projection.intervals[-1].storage_energy_at_end_wh + 1e-6 >= terminal_wh
    )
    if not comparable_windows:
        if cacheable:
            assert equivalent_cache is not None
            equivalent_cache[cache_key] = None
        return None
    windows = replace(windows, windows=comparable_windows, rejected_windows=())
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=retained.valid_until)
    settlement = IndependentDailyFinancialSettlement()
    cash = {
        w.schedule.schedule_id: round(
            settlement.settle_planning_basis(
                projection=w.projection, tariffs=tariffs
            ).cash_result_eur,
            12,
        )
        for w in comparable_windows
    }
    # Exact lower-bound pruning, not a heuristic shortlist: all windows are
    # settled first. A strictly more expensive window cannot beat a valid one
    # under this financial-only objective. Equal-cost windows stay together;
    # if every member fails canonical admission, assess the next cost group.
    evaluation = None
    selected = None
    for value in sorted(set(cash.values()), reverse=True):
        group = tuple(w for w in comparable_windows if cash[w.schedule.schedule_id] == value)
        portfolio = produce_main_charge_portfolio(
            snapshot=snapshot,
            windows=replace(windows, windows=group),
            tariffs=tariffs,
            opportunity_ids=(),
        )
        outcomes = tuple(
            replace(
                o,
                objective_outcomes=(
                    ObjectiveOutcome(
                        ObjectiveKind.FINANCIAL_RESULT,
                        value,
                        ComparisonDirection.HIGHER_IS_BETTER,
                        "EUR",
                        o.confidence,
                        (snapshot.snapshot_id,),
                    ),
                ),
            )
            for o in portfolio.outcome_set.outcomes
        )
        from picot.domain.objectives import ObjectiveWeight, WeightedObjective

        strategy = replace(
            portfolio.strategy,
            objectives=(WeightedObjective(ObjectiveKind.FINANCIAL_RESULT, ObjectiveWeight(1000)),),
        )
        outcome_set = CandidateOutcomeSet(
            snapshot.snapshot_id,
            strategy.strategy_version,
            EvaluationEngine.candidate_set_reference(portfolio.candidate_set),
            outcomes,
        )
        evaluation = EvaluationEngine().evaluate(
            portfolio.candidate_set, strategy, outcome_set, created_at=snapshot.captured_at
        )
        if evaluation.winning_candidate is not None:
            selected = next(
                s.window
                for s in portfolio.sources
                if s.candidate_id == evaluation.winning_candidate.candidate_id
            )
            break
    if evaluation is None or evaluation.winning_candidate is None:
        if reused:
            return rebuilt_selection(snapshot, request, retained, conversion, terminal_wh)
        return None
    plans = (
        ExecutionPlanBuilder()
        .build(evaluation, created_at=snapshot.captured_at, fallback_policy_id="guarded-nom")
        .plans
    )
    if len(plans) != 1:
        raise ValueError("joint_ev_requires_single_battery_plan")
    plan = replace(plans[0], solcast_planning_basis=snapshot.solcast_planning_basis)
    selection = JointEVSelection(
        snapshot, dict(request), retained.plan_id, plan, selected, trigger, evaluation
    )
    if cacheable:
        assert equivalent_cache is not None
        equivalent_cache[cache_key] = selection
    return selection
