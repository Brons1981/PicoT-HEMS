"""Translate selected simulated market volumes into explicit Store evidence."""

from dataclasses import replace

from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.evaluation import EvaluationRecord
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.market_plan_revision import MarketPlanRevision
from picot.v2.contracts import PlanningInputSnapshot


def build_market_plan_revisions(
    *, snapshot: PlanningInputSnapshot, plan: ExecutionPlan,
    window: DailyMainChargeWindow, evaluation_record: EvaluationRecord,
) -> tuple[MarketPlanRevision, ...]:
    """Copy a canonical winner; never select, price or dispatch a market action."""
    context = snapshot.daily_charge_context
    if context is None or not context.market_plan_bindings:
        return ()
    if snapshot.snapshot_id != plan.snapshot_id or snapshot.captured_at != plan.created_at or (
        window.schedule.snapshot_id != snapshot.snapshot_id
    ):
        raise ValueError("market revision source must match the selected snapshot")
    active = tuple(p for p in context.main_plans
                   if p.plan_id in context.active_main_plan_ids
                   and p.execution_scope_id == plan.execution_scope_id)
    if len(active) != 1:
        raise ValueError("market revision requires exactly one current active plan")
    revisions = []
    for old in context.market_plan_bindings:
        if old.execution_scope_id != plan.execution_scope_id:
            continue
        progress = next((p for p in context.market_execution_progress
                         if p.assignment_id == old.assignment_id), None)
        if progress is not None and progress.stop_requested_at is not None:
            continue
        previous = next(p for p in context.main_plans if p.plan_id == old.plan_id)
        parts = tuple(s for s in previous.segments if s.segment_id in old.segment_ids)
        if parts[-1].ends_at <= plan.created_at:
            continue
        available = sum(
            amount * max(0.0, (s.ends_at - max(s.starts_at, plan.created_at)).total_seconds())
            / (s.ends_at - s.starts_at).total_seconds()
            for s, amount in zip(parts, old.segment_export_wh, strict=True)
        )
        retained = tuple(s for s in plan.segments if s.purpose == old.assignment_id)
        energies = []
        draw = 0.0
        for segment in retained:
            energies.append(sum(
                interval.storage_export_target_wh * max(0.0, (
                    min(interval.ends_at, segment.ends_at)
                    - max(interval.starts_at, segment.starts_at)
                ).total_seconds()) / (interval.ends_at - interval.starts_at).total_seconds()
                for interval in window.schedule.intervals
                if interval.intent is DailyStorageIntent.STORAGE_EXPORT
            ))
            draw += sum(
                (i.storage_to_household_output_wh + i.storage_to_grid_output_wh
                 + i.storage_discharge_loss_wh) * max(0.0, (
                    min(i.ends_at, segment.ends_at) - max(i.starts_at, segment.starts_at)
                ).total_seconds()) / (i.ends_at - i.starts_at).total_seconds()
                for i in window.projection.intervals
            )
        remaining = sum(energies)
        if remaining > available + 1e-6:
            raise ValueError("selected market revision cannot replenish remaining export")
        cancelled = old.cancelled_export_wh + max(0.0, available - remaining)
        elapsed = max(0.0, old.expected_export_wh - old.cancelled_export_wh - available)
        binding = replace(
            old, plan_id=plan.plan_id, snapshot_id=plan.snapshot_id,
            segment_ids=tuple(s.segment_id for s in retained), segment_export_wh=tuple(energies),
            elapsed_planned_export_wh=elapsed, cancelled_export_wh=cancelled,
            expected_battery_draw_wh=draw,
            original_plan_id=old.original_plan_id or old.plan_id,
            original_segment_ids=old.original_segment_ids or old.segment_ids,
        ) if retained else None
        revision = MarketPlanRevision(
            old, active[0].plan_id, evaluation_record, plan.winning_energy_path_id, binding,
            "market_route_removed" if binding is None else "market_route_shortened"
            if cancelled > old.cancelled_export_wh + 1e-6 else "market_route_retained",
        )
        revision.validate_plan(plan)
        revisions.append(revision)
    return tuple(revisions)
