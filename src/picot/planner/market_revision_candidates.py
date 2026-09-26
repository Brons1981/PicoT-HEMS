"""Unranked market revisions through the existing daily physical simulator."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from picot.domain.daily_reference_charge_window import (
    DailyMainChargeSegment,
    DailyMainChargeWindow,
    DailyMainChargeWindowSet,
    DailyMainRejectedWindow,
)
from picot.domain.daily_reference_intent import DailyReferenceIntentInterval
from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
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


def market_revision_available(snapshot: PlanningInputSnapshot) -> bool:
    context = snapshot.daily_charge_context
    return context is not None and any(
        binding.plan_id in context.active_main_plan_ids
        and not any(p.assignment_id == binding.assignment_id and p.stop_requested_at is not None
                    for p in context.market_execution_progress)
        and any(s.segment_id in binding.segment_ids and s.ends_at > snapshot.captured_at
                for p in context.main_plans if p.plan_id == binding.plan_id for s in p.segments)
        for binding in context.market_plan_bindings
    )


def market_revision_windows(
    *, snapshot: PlanningInputSnapshot,
    trigger: DailyBridgeTrigger | DailyMainShortfallTrigger | DailyMainPVSurplusTrigger,
    conversion_model: StorageConversionModel, wear_eur_per_kwh: float = 0.0,
) -> DailyMainChargeWindowSet:
    """Retain, shorten or remove one pending daily trade, without selecting it.

    Other trades retain their identity and segments. Repeated admitted reviews
    may revisit the resulting plan; this search never creates another day budget.
    Missing tomorrow coverage is evidence against economic revision, not an
    invented forecast or an exception that destroys valid current execution.
    """
    context = snapshot.daily_charge_context
    assert context is not None
    owner = next(a for a in context.assignments if a.assignment_id == trigger.assignment_id)
    trigger.validate(owner, snapshot.snapshot_id, snapshot.captured_at)
    active = next(p for p in context.main_plans if p.plan_id == trigger.active_plan_id)
    available = tuple((binding, tuple(s for s in active.segments
                                      if s.segment_id in binding.segment_ids
                                      and s.ends_at > snapshot.captured_at))
                      for binding in context.market_plan_bindings
                      if binding.plan_id == active.plan_id and not any(
                          p.assignment_id == binding.assignment_id
                          and p.stop_requested_at is not None
                          for p in context.market_execution_progress))
    binding, parts = min((pair for pair in available if pair[1]),
                         key=lambda pair: pair[1][0].starts_at)
    local_day = snapshot.captured_at.astimezone(ZoneInfo("Europe/Amsterdam")).date()
    required_end = datetime.combine(local_day + timedelta(days=2), time.min,
                                    ZoneInfo("Europe/Amsterdam")).astimezone(UTC)
    assert snapshot.horizon_end is not None
    tariff_adapter = IndependentDailyTariffAdapter()
    end = tariff_adapter.published_horizon_end(
        snapshot, maximum_horizon_end=min(required_end, snapshot.horizon_end),
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
        # Only the financial extension is unavailable. Revalidate the full
        # committed horizon and allow ordinary charge repair there; the partial
        # basis below cannot establish a financial reason to change export.
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
        binding.assignment_id, active.plan_id, end, required_end, end == required_end,
        sum(baseline.intervals[n].storage_export_target_wh for n in export_indexes),
        tuple((baseline.intervals[n].starts_at, baseline.intervals[n].ends_at)
              for n in export_indexes), wear_eur_per_kwh,
        tuple(a.assignment_id for a in context.assignments
              if a.execution_scope_id == owner.execution_scope_id
              and a.completed_at is None and a.route_plan_id is None
              and a.starts_at < required_end and a.ends_at > snapshot.captured_at),
    )
    seeds = [baseline]
    # A future window can be shortened at either edge; a begun action cannot
    # be paused and restarted as a second action. Every retained slice is
    # contiguous inside the original window, at the original physical power.
    starts = range(len(export_indexes)) if snapshot.captured_at < parts[0].starts_at else range(1)
    slices = [()] + [export_indexes[start:stop] for start in starts
                     for stop in range(start + 1, len(export_indexes) + 1)
                     if (start, stop) != (0, len(export_indexes))]
    for keep in slices:
        removed = set(export_indexes) - set(keep)
        intents = tuple(replace(i, intent=Intent.NOM, storage_export_target_wh=0.0)
                        if n in removed else i for n, i in enumerate(baseline.intervals))
        digest = sha256(repr((snapshot.snapshot_id, intents)).encode()).hexdigest()[:20]
        seeds.append(replace(baseline, intervals=intents, schedule_id="market-revision:" + digest))
    windows: dict[tuple[DailyReferenceIntentInterval, ...], DailyMainChargeWindow] = {}
    rejected: dict[tuple[DailyReferenceIntentInterval, ...], DailyMainRejectedWindow] = {}
    simulations = 0
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
