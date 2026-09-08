"""Durable market stop/skip decisions at the existing execution boundary."""

from dataclasses import replace

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_execution import MarketExecutionProgress
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.market_export_measurement import measured_market_export
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


def guarded_market_primitive(
    *,
    snapshot: PlanningInputSnapshot,
    store: ActivePlanCommitmentStore,
    scope_id: str,
    requested: ExecutionPrimitive,
    export_mode_confirmed: bool,
    ownership_lost: bool = False,
) -> ExecutionPrimitive:
    now = snapshot.captured_at
    assignments = {a.assignment_id: a for a in store.load_market_daily_assignments()}
    mode = snapshot.storage_mode_capability_evidence
    result = requested
    for binding in store.load_market_plan_bindings():
        if binding.execution_scope_id != scope_id:
            continue
        assignment = assignments[binding.assignment_id]
        plan = store.load_market_original_plan(binding)
        original_ids = binding.original_segment_ids or binding.segment_ids
        parts = tuple(s for s in plan.segments if s.segment_id in original_ids)
        start, end = parts[0].starts_at, parts[-1].ends_at
        due = start <= now < end
        if assignment.status != "pending":
            if due and requested is ExecutionPrimitive.DISCHARGE_AT_POWER:
                result = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            continue
        progress = store.load_market_progress(binding.assignment_id) or MarketExecutionProgress(
            binding.assignment_id
        )
        if now < start:
            continue
        if ownership_lost and progress.started_at is None:
            continue
        state = next(
            (s for s in snapshot.current_storage_states if s.execution_scope_id == scope_id), None
        )
        limits = next(
            (s for s in snapshot.storage_physical_limits if s.execution_scope_id == scope_id), None
        )
        if state is None or limits is None:
            return ExecutionPrimitive.BALANCE_BIDIRECTIONAL
        if progress.started_at is None and export_mode_confirmed and due:
            changed = mode.state_changed_at if mode is not None else None
            confirmed_at = changed if changed is not None and start <= changed <= now else now
            progress = replace(progress, started_at=confirmed_at)
        if progress.started_at is None:
            if due and measured_market_export(snapshot.market_power_history, now, now) is None:
                result = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                continue
            reason = None
            if now >= end:
                reason = "market_window_missed"
            elif binding.expected_battery_draw_wh is None:
                reason = "market_start_soc_evidence_missing"
            elif state.current_stored_energy_wh + 1e-6 < (
                limits.minimum_soc * state.usable_capacity_wh + binding.expected_battery_draw_wh
            ):
                reason = "market_start_soc_insufficient"
            if reason:
                progress = replace(progress, stop_requested_at=now, reason=reason)
                store.save_market_progress(progress)
                if due:
                    result = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            continue
        measured_until = progress.stopped_at or now
        if not export_mode_confirmed or ownership_lost:
            changed = mode.state_changed_at if mode is not None else None
            stopped = (
                changed
                if not ownership_lost
                and changed is not None
                and progress.started_at <= changed <= now
                else now
            )
            progress = replace(
                progress,
                stop_requested_at=progress.stop_requested_at or stopped,
                stopped_at=progress.stopped_at or stopped,
                reason=progress.reason or "market_mode_ended",
            )
            assert progress.stopped_at is not None
            measured_until = progress.stopped_at
        assert progress.started_at is not None
        measured = measured_market_export(
            snapshot.market_power_history, progress.started_at, measured_until
        )
        if measured is not None:
            progress = replace(progress, measured_export_wh=measured)
        elif progress.stopped_at is not None:
            progress = replace(progress, measured_export_wh=None)
            assert progress.started_at is not None and progress.stopped_at is not None
            history = snapshot.market_power_history
            if (
                history is not None
                and history.status == "available"
                and (
                    history.starts_at
                    <= progress.started_at
                    <= progress.stopped_at
                    <= history.ends_at
                )
            ):
                progress = replace(progress, measurement_unavailable=True)
        if progress.stop_requested_at is None:
            reason = (
                "market_window_ended"
                if now >= end
                else "market_minimum_soc_reached"
                if state.current_soc <= limits.minimum_soc
                else "market_export_budget_reached"
                if measured is not None and measured >= binding.expected_export_wh
                else "market_export_measurement_unavailable"
                if measured is None
                else None
            )
            if reason:
                progress = replace(progress, stop_requested_at=now, reason=reason)
        store.save_market_progress(progress)
        if due and progress.stop_requested_at is not None:
            result = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
    return result
