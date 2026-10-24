"""Read-only energy outlook from the retained route, not an energy allocation.

No device requests, MEP candidates, commitments or execution writes. In
particular, projected storage margins are correlated and are not spendable
budgets. Additional demand still requires a full plan assessment.
"""

from datetime import timedelta
from math import ceil, isfinite
from typing import Any, TypedDict

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    IndependentDailyReferenceAdapter,
)

CONTRACT = "hems-energy-outlook:v1"
ENTITY = "sensor.picot_energy_outlook"


class OutlookSlot(TypedDict):
    starts_at: str
    ends_at: str
    storage_minimum_wh: float
    storage_margin_wh: float
    pv_export_wh: float
    grid_import_wh: float
    confidence: float


def outlook(
    snapshot: PlanningInputSnapshot, conversion_model: StorageConversionModel
) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        contract=CONTRACT,
        snapshot_id=snapshot.snapshot_id,
        generated_at=snapshot.captured_at.isoformat(),
        valid_until=(snapshot.captured_at + timedelta(seconds=180)).isoformat(),
        status="blocked",
        reason="retained_plan_unavailable",
        advisory_only=True,
        approval_required=True,
        budgets_additive=False,
        available_additional_energy_wh=None,
        slots=[],
    )
    context = snapshot.daily_charge_context
    plans = (
        [
            p
            for p in context.main_plans
            if p.plan_id in context.active_main_plan_ids
            and p.valid_from <= snapshot.captured_at < p.valid_until
        ]
        if context
        else []
    )
    if context is None or context.status != "ready" or len(plans) != 1:
        return result
    try:
        adapter = IndependentDailyReferenceAdapter()
        invalid = adapter.committed_execution_invalidity_reasons(
            snapshot=snapshot, plan=plans[0], conversion_model=conversion_model
        )
        if invalid:
            return dict(result, reason="retained_plan_requires_repair")
        projection, _ = adapter.committed_plan_projection(
            snapshot=snapshot, plan=plans[0], conversion_model=conversion_model
        )
        (storage,) = snapshot.current_storage_states
        (limits,) = [
            p
            for p in snapshot.storage_physical_limits
            if p.capability_id == storage.capability_id
            and p.execution_scope_id == storage.execution_scope_id
        ]
        floor = limits.minimum_soc * storage.usable_capacity_wh
        intervals = projection.intervals
        if not intervals or len(intervals) > 2000:
            raise ValueError("projection_size")
        # At most 24 contiguous groups, no dropped intervals and no invented splits.
        size = ceil(len(intervals) / 24)
        slots: list[OutlookSlot] = []
        for offset in range(0, len(intervals), size):
            group = intervals[offset : offset + size]
            low = min(min(i.storage_energy_at_start_wh, i.storage_energy_at_end_wh) for i in group)
            slots.append(
                OutlookSlot(
                    starts_at=group[0].starts_at.isoformat(),
                    ends_at=group[-1].ends_at.isoformat(),
                    storage_minimum_wh=round(low, 3),
                    storage_margin_wh=round(max(0, low - floor), 3),
                    pv_export_wh=round(sum(i.pv_to_grid_wh for i in group), 3),
                    grid_import_wh=round(
                        sum(i.grid_to_household_wh + i.grid_to_storage_input_wh for i in group), 3
                    ),
                    confidence=round(min(i.confidence for i in group), 3),
                )
            )
        if any(
            not isfinite(v) for slot in slots for v in slot.values() if isinstance(v, (float, int))
        ):
            raise ValueError("nonfinite_projection")
        return dict(
            result,
            status="ready",
            reason="retained_route_forecast",
            retained_plan_id=plans[0].plan_id,
            horizon_start=slots[0]["starts_at"],
            horizon_end=slots[-1]["ends_at"],
            storage_floor_wh=round(floor, 3),
            projected_minimum_margin_wh=min(s["storage_margin_wh"] for s in slots),
            confidence=min(s["confidence"] for s in slots),
            basis=projection.basis_method,
            slots=slots,
        )
    except (ValueError, TypeError, ArithmeticError):
        return dict(result, reason="projection_unavailable")
