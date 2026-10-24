"""Read-only recharge discovery using the ordinary, device-unaware planner.

A result is conditional: only a subsequent committed-route assessment can
authorize a load. Unsupported shortages remain rejected, never invented goals.
"""

from dataclasses import replace

from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_bridge import energy_deficits
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.reserve_recharge import ReserveWindow


def _ordinary(
    snapshot: PlanningInputSnapshot, conversion_model: StorageConversionModel,
    retained: ExecutionPlan, terminal: float,
) -> DailyMainChargeWindow | None:
    snapshot = replace(snapshot, horizon_end=retained.valid_until)
    adapter = IndependentDailyReferenceAdapter()
    context = snapshot.daily_charge_context
    if context is None or snapshot.external_load_policy is not None:
        return None
    triggers = adapter.main_repair_sequence(
        snapshot=snapshot,
        triggers=adapter.main_route_shortfalls(
            snapshot=snapshot, conversion_model=conversion_model
        ),
        conversion_model=conversion_model,
    )
    if triggers:
        # One normal planning cycle repairs one owner. Do not promise a chain
        # of hypothetical repairs or relax another day's obligation.
        if len(triggers) != 1:
            return None
        trigger = triggers[0]
        owner = next(a for a in context.assignments if a.assignment_id == trigger.assignment_id)
        windows = adapter.main_charge_windows(
            snapshot=snapshot,
            assignment=owner,
            conversion_model=conversion_model,
            optimisation_trigger=trigger,
        )
    else:
        bridge = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion_model)
        if bridge.trigger is None:
            return None
        windows = adapter.bridge_windows(
            snapshot=snapshot,
            trigger=bridge.trigger,
            conversion_model=conversion_model,
        )
    _, existing = adapter.committed_plan_projection(
        snapshot=snapshot,
        plan=retained,
        conversion_model=conversion_model,
    )
    limit = snapshot.storage_physical_limits[0]
    candidates = tuple(
        w
        for w in windows.windows
        if w.schedule.horizon_start == existing.horizon_start
        and w.schedule.horizon_end == existing.horizon_end
        and adapter._same_exports(existing, w.schedule)
        and adapter._retirement_exports_valid(w.schedule, w.projection)
        and w.projection.intervals[-1].storage_energy_at_end_wh + 1e-6 >= terminal
        and not any(
            i.deficit_wh > 1e-6
            for i in energy_deficits(
                w.projection,
                w.schedule,
                until=retained.valid_until,
                maximum_discharge_output_power_w=limit.maximum_discharge_output_power_w,
            )
        )
    )
    if not candidates:
        return None
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=retained.valid_until)
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot,
        windows=replace(windows, windows=candidates),
        tariffs=tariffs,
        opportunity_ids=(),
    )
    evaluation = EvaluationEngine().evaluate(
        portfolio.candidate_set,
        portfolio.strategy,
        portfolio.outcome_set,
        created_at=snapshot.captured_at,
    )
    chosen = next(
        (s for s in portfolio.sources if s.candidate_id == evaluation.record.winning_candidate_id),
        None,
    )
    return chosen.window if chosen else None


def discover(
    snapshot: PlanningInputSnapshot, conversion_model: StorageConversionModel,
    retained: ExecutionPlan, terminal: float,
) -> DailyMainChargeWindow | ReserveWindow | None:
    # First retain the established daily/bridge repair policy. Reserve-only
    # acquisition is a separate generic portfolio with no fabricated daily goal.
    try:
        ordinary = _ordinary(snapshot, conversion_model, retained, terminal)
    except ValueError:
        ordinary = None
    if ordinary is not None:
        return ordinary
    from picot.v2.reserve_recharge import portfolio

    required = (retained.execution_scope_id, retained.valid_until, terminal)
    changed = replace(
        snapshot,
        storage_reserve_checkpoints=tuple(
            sorted(set(snapshot.storage_reserve_checkpoints + (required,)))
        ),
    )
    options = portfolio(changed, retained, conversion_model)
    if options is None:
        return None
    comparable = options.comparable
    result = EvaluationEngine().evaluate(
        comparable.candidate_set,
        comparable.strategy,
        comparable.outcome_set,
        created_at=snapshot.captured_at,
    )
    winner = result.record.winning_candidate_id
    return options.windows.get(winner) if winner is not None else None
