"""Unranked market revisions through the existing daily physical simulator."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from picot.domain.daily_reference_charge_window import (
    DailyMainChargeSegment,
    DailyMainChargeWindow,
    DailyMainChargeWindowSet,
    DailyMainRejectedWindow,
)
from picot.domain.daily_reference_intent import DailyReferenceIntentInterval
from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
from picot.domain.execution_plan import ExecutionPlanSegment
from picot.domain.market_plan_binding import MarketPlanBinding
from picot.domain.market_revision_comparison import MarketRevisionBasis
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_bridge import DailyBridgeTrigger
from picot.v2.daily_charge_assignment import DailyMainShortfallTrigger
from picot.v2.daily_pv_comparison import DailyMainPVSurplusTrigger
from picot.v2.independent_daily_reference_adapter import (
    DailyReferenceInputError,
    IndependentDailyReferenceAdapter,
)
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter


class MarketRevisionCoverageUnavailable(ValueError):
    """No priced comparison can cover the already committed next daily goal."""


def _eligible_bindings(
    snapshot: PlanningInputSnapshot,
    trigger: DailyBridgeTrigger | DailyMainShortfallTrigger | DailyMainPVSurplusTrigger | None,
) -> tuple[tuple[MarketPlanBinding, tuple[ExecutionPlanSegment, ...]], ...]:
    context = snapshot.daily_charge_context
    if context is None:
        return ()
    owner = next((a for a in context.assignments
                  if trigger is not None and a.assignment_id == trigger.assignment_id), None)
    if trigger is not None:
        if owner is None:
            return ()
        trigger.validate(owner, snapshot.snapshot_id, snapshot.captured_at)
    available = []
    for binding in context.market_plan_bindings:
        if (binding.plan_id not in context.active_main_plan_ids
            or trigger is not None and binding.plan_id != trigger.active_plan_id) or any(
            p.assignment_id == binding.assignment_id and p.stop_requested_at is not None
            for p in context.market_execution_progress
        ):
            continue
        parts = tuple(s for p in context.main_plans if p.plan_id == binding.plan_id
                      for s in p.segments if s.segment_id in binding.segment_ids
                      and s.ends_at > snapshot.captured_at)
        if not parts:
            continue
        # A bridge owns the need before the next charge. A daily repair owns
        # its delivery day, never the export after another day's full charge.
        if isinstance(trigger, DailyBridgeTrigger):
            if parts[-1].ends_at > trigger.next_starts_at:
                continue
        elif owner is not None and parts[-1].ends_at > owner.ends_at:
            continue
        available.append((binding, parts))
    return tuple(available)


def market_revision_available(
    snapshot: PlanningInputSnapshot,
    trigger: (
        DailyBridgeTrigger | DailyMainShortfallTrigger | DailyMainPVSurplusTrigger | None
    ) = None,
) -> bool:
    return bool(_eligible_bindings(snapshot, trigger))


def market_revision_windows(
    *, snapshot: PlanningInputSnapshot,
    trigger: DailyBridgeTrigger | DailyMainShortfallTrigger | DailyMainPVSurplusTrigger,
    conversion_model: StorageConversionModel, wear_eur_per_kwh: float = 0.0,
) -> DailyMainChargeWindowSet:
    """Retain, shorten or remove one pending daily trade, without selecting it.

    Other trades retain their identity and segments. Repeated admitted reviews
    may revisit the resulting plan; this search never creates another day budget.
    Missing recovery coverage is evidence against economic revision, not an
    invented forecast or an exception that destroys valid current execution.
    """
    context = snapshot.daily_charge_context
    assert context is not None
    owner = next(a for a in context.assignments if a.assignment_id == trigger.assignment_id)
    trigger.validate(owner, snapshot.snapshot_id, snapshot.captured_at)
    active = next(p for p in context.main_plans if p.plan_id == trigger.active_plan_id)
    available = _eligible_bindings(snapshot, trigger)
    if not available:
        raise ValueError("market_revision_outside_trigger_scope")
    binding, parts = min(available, key=lambda pair: pair[1][0].starts_at)
    # Recovery must belong to an unchanged subsequent charge cycle. The
    # charging repair remains available even if no comparable cycle is known.
    recovery = next(iter(sorted((a for a in context.assignments
        if a.completed_at is None and a.main_segments
        and a.execution_scope_id == owner.execution_scope_id
        and min(s.starts_at for s in a.main_segments) >= parts[-1].ends_at
        and (isinstance(trigger, DailyBridgeTrigger) or a.assignment_id != owner.assignment_id)),
        key=lambda a: min(s.starts_at for s in a.main_segments))), None)
    required_end = (max(s.ends_at for s in recovery.main_segments)
                    if recovery is not None else active.valid_until)
    assert snapshot.horizon_end is not None
    tariff_adapter = IndependentDailyTariffAdapter()
    end = tariff_adapter.published_horizon_end(
        snapshot, maximum_horizon_end=snapshot.horizon_end,
    )
    if end < max(s.ends_at for s in owner.main_segments):
        raise MarketRevisionCoverageUnavailable(
            "market_revision_prices_do_not_cover_committed_main_goal")
    adapter = IndependentDailyReferenceAdapter()
    try:
        inputs = adapter._inputs(snapshot, horizon_end=end, maximum_duration=timedelta(hours=49))
    except DailyReferenceInputError as exc:
        if end <= active.valid_until or str(exc) not in {
            "daily_reference_household_horizon_incomplete", "daily_reference_pv_gap",
            "daily_reference_pv_coverage_incomplete", "daily_reference_pv_range_incomplete",
        }:
            raise
        # Missing forecasts beyond the committed plan do not erase that plan.
        # Revalidate its full horizon; recovery inside it may still be priced.
        end = active.valid_until
        inputs = adapter._inputs(snapshot, horizon_end=end, maximum_duration=timedelta(hours=49))
    baseline, retained = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
    )
    assert baseline is not None
    export_indexes = tuple(n for n, i in enumerate(baseline.intervals)
                           if i.intent is Intent.STORAGE_EXPORT and any(
                               s.starts_at <= i.starts_at < i.ends_at <= s.ends_at for s in parts))
    basis = MarketRevisionBasis(
        binding.assignment_id, active.plan_id, end, required_end,
        recovery is not None and end >= required_end,
        sum(baseline.intervals[n].storage_export_target_wh for n in export_indexes),
        tuple((baseline.intervals[n].starts_at, baseline.intervals[n].ends_at)
              for n in export_indexes), wear_eur_per_kwh,
        tuple(a.assignment_id for a in context.assignments
              if a.execution_scope_id == owner.execution_scope_id
              and a.completed_at is None and a.route_plan_id is None
              and a.starts_at < required_end and a.ends_at > snapshot.captured_at),
        recovery.assignment_id if recovery is not None else None,
        ((min(s.starts_at for s in recovery.main_segments), required_end),)
        if recovery is not None else (),
    )
    seeds = [baseline]
    baseline_projection = adapter._bridge_projection(snapshot, inputs, baseline, conversion_model)
    pv_surplus = {n for n, i in enumerate(baseline_projection.intervals)
                  if i.usable_pv_wh > i.household_demand_wh + 1e-6}
    # A future window can be shortened at either edge; a begun action cannot
    # be paused and restarted as a second action. Every retained slice is
    # contiguous inside the original window, at the original physical power.
    starts = range(len(export_indexes)) if snapshot.captured_at < parts[0].starts_at else range(1)
    slices = [()] + [export_indexes[start:stop] for start in starts
                     for stop in range(start + 1, len(export_indexes) + 1)
                     if (start, stop) != (0, len(export_indexes))]
    for keep in slices:
        removed = set(export_indexes) - set(keep)
        intents = tuple(replace(i, intent=Intent.NOM if n in pv_surplus
                                else Intent.HOUSEHOLD_SUPPORT_ONLY, storage_export_target_wh=0.0)
                        if n in removed else i for n, i in enumerate(baseline.intervals))
        digest = sha256(repr((snapshot.snapshot_id, intents)).encode()).hexdigest()[:20]
        seeds.append(replace(baseline, intervals=intents, schedule_id="market-revision:" + digest))
    windows: dict[tuple[DailyReferenceIntentInterval, ...], DailyMainChargeWindow] = {}
    rejected: dict[tuple[DailyReferenceIntentInterval, ...], DailyMainRejectedWindow] = {}
    simulations = 1
    for seed in seeds:
        if isinstance(trigger, DailyBridgeTrigger):
            discovered = adapter.bridge_windows(snapshot=snapshot, trigger=trigger,
                                                 conversion_model=conversion_model,
                                                 revision_schedule=seed)
        else:
            discovered = adapter.main_charge_windows(
                snapshot=snapshot, assignment=owner, conversion_model=conversion_model,
                optimisation_trigger=trigger, revision_schedule=seed,
            )
        simulations += discovered.simulation_count
        for window in discovered.windows:
            windows.setdefault(window.schedule.intervals, window)
        for attempt in discovered.rejected_windows:
            rejected.setdefault(attempt.schedule.intervals, attempt)
        if not discovered.windows and not discovered.rejected_windows:
            projection = adapter._bridge_projection(snapshot, inputs, seed, conversion_model)
            simulations += 1
            main = tuple(DailyMainChargeSegment(
                "market-attempt:" + r.segment.segment_id,
                max(seed.horizon_start, r.segment.starts_at),
                min(seed.horizon_end, r.segment.ends_at),
                next(i.intent for i in seed.intervals
                     if r.segment.starts_at <= i.starts_at < r.segment.ends_at),
            ) for r in retained if r.assignment_id == owner.assignment_id)
            rejected.setdefault(seed.intervals, DailyMainRejectedWindow(
                owner.assignment_id, "hybrid", seed, main, projection,
                inputs.storage.usable_capacity_wh,
                (discovered.reason or "daily_main_no_feasible_window",),
                tuple(r for r in retained if r.assignment_id != owner.assignment_id),
            ))
    # A fresh incumbent is added downstream with its own canonical identity.
    windows.pop(baseline.intervals, None)
    rejected.pop(baseline.intervals, None)
    for key in windows:
        rejected.pop(key, None)
    return DailyMainChargeWindowSet(
        owner.assignment_id, snapshot.snapshot_id, tuple(windows.values()),
        "discovered" if windows else "unreachable", "financial_market_revision", simulations,
        purpose="bridge" if isinstance(trigger, DailyBridgeTrigger) else "main_charge",
        rejected_windows=tuple(rejected.values()), market_revision=basis,
    )
