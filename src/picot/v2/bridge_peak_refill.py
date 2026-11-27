"""Offer a bounded household-support and later refill alternative."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_simulation import DailyPlanningProjection
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot

PEAK_REFILL_PREFIX = "bridge-peak-refill:"


def has_cheaper_refill(
    snapshot: PlanningInputSnapshot,
    schedule: DailyReferenceIntentSchedule,
    projection: DailyPlanningProjection,
    until: datetime,
    conversion: StorageConversionModel,
    minimum_energy_wh: float,
) -> bool:
    efficiency = conversion.charge_efficiency * conversion.discharge_efficiency
    peak: float | None = None
    for action, flow in zip(schedule.intervals, projection.intervals, strict=True):
        if action.ends_at > until:
            break
        rate = next((p.value_eur_per_kwh for p in snapshot.price_points
                     if p.starts_at <= action.starts_at and action.ends_at <= p.ends_at), None)
        if rate is None:
            continue
        if peak is not None and rate / efficiency < peak:
            return True
        if (action.intent is DailyStorageIntent.STANDBY
                and flow.storage_energy_at_start_wh > minimum_energy_wh + 1e-6
                and flow.grid_to_household_wh - flow.battery_excluded_demand_wh > 1e-6):
            peak = rate if peak is None else max(peak, rate)
    return False


def peak_refill_energy(
    reference: DailyPlanningProjection, proposal: DailyPlanningProjection,
) -> tuple[float, float]:
    """Measure household import avoided before the first extra refill interval."""
    avoided = refill = 0.0
    for old, new in zip(reference.intervals, proposal.intervals, strict=True):
        extra = new.grid_to_storage_input_wh - old.grid_to_storage_input_wh
        if refill <= 1e-6 and extra <= 1e-6:
            avoided += max(0.0, old.grid_to_household_wh - new.grid_to_household_wh)
        refill += max(0.0, extra)
    return avoided, refill


def peak_refill_candidates(
    *,
    support: tuple[DailyReferenceIntentInterval, ...],
    reference: DailyPlanningProjection,
    free_prices: dict[int, float],
    round_trip_efficiency: float,
    next_starts_at: datetime,
    schedule_for: Callable[
        [tuple[DailyReferenceIntentInterval, ...]], DailyReferenceIntentSchedule
    ],
    project: Callable[[DailyReferenceIntentSchedule], DailyPlanningProjection],
) -> tuple[DailyReferenceIntentSchedule, ...]:
    """Try later low-price charging with the reference's terminal inventory."""
    main_index = next(i for i, interval in enumerate(reference.intervals)
                      if interval.starts_at == next_starts_at)
    target_wh = reference.intervals[main_index].storage_energy_at_start_wh
    terminal_wh = reference.intervals[-1].storage_energy_at_end_wh
    targets: list[tuple[float, int, float]] = []
    peak_price: float | None = None
    for index, rate in sorted(free_prices.items()):
        if peak_price is not None and rate / round_trip_efficiency < peak_price:
            targets.append((rate, index, peak_price))
        interval = reference.intervals[index]
        if interval.grid_to_household_wh + interval.storage_to_household_output_wh > 1e-6:
            peak_price = rate if peak_price is None else max(peak_price, rate)

    alternatives = []
    for rate, start, peak in sorted(targets)[:6]:
        earlier = tuple(
            replace(i, intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY)
            if n < start and n in free_prices and free_prices[n] > rate / round_trip_efficiency
            and i.intent is DailyStorageIntent.GRID_REQUIREMENT else i
            for n, i in enumerate(support)
        )
        end = start + 1
        while end in free_prices and free_prices[end] / round_trip_efficiency < peak:
            end += 1

        def trial(
            stop: int, start: int = start,
            earlier: tuple[DailyReferenceIntentInterval, ...] = earlier,
        ) -> DailyReferenceIntentSchedule:
            return schedule_for(tuple(
                replace(i, intent=DailyStorageIntent.GRID_REQUIREMENT)
                if start <= n < stop else i for n, i in enumerate(earlier)
            ))

        low, high = start + 1, end
        while low < high:
            mid = (low + high) // 2
            trial_wh = project(trial(mid)).intervals[main_index].storage_energy_at_start_wh
            if trial_wh >= target_wh - 1e-6:
                high = mid
            else:
                low = mid + 1
        candidate = trial(low)
        projected = project(candidate)
        if (projected.intervals[main_index].storage_energy_at_start_wh < target_wh - 1e-6
                or abs(projected.intervals[-1].storage_energy_at_end_wh - terminal_wh) > 1e-6):
            continue
        if not any(i.grid_to_storage_input_wh > 1e-6 for i in projected.intervals[start:low]):
            continue
        alternatives.append(replace(
            candidate, schedule_id=PEAK_REFILL_PREFIX + candidate.schedule_id,
        ))
    return tuple(alternatives)
