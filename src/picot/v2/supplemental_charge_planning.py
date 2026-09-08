"""Candidate-owned supplemental goals; no ranking, persistence or execution."""

from dataclasses import replace
from hashlib import sha256

from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.supplemental_charge import SupplementalChargeAssignment
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_bridge import DailyBridgeTrigger


def attach_supplemental_goals(
    window: DailyMainChargeWindow,
    snapshot: PlanningInputSnapshot,
    trigger: DailyBridgeTrigger | None = None,
) -> DailyMainChargeWindow | None:
    """Admit only routes that preserve every still-open supplemental target."""
    context = snapshot.daily_charge_context
    if context is None:
        if trigger is not None:
            raise ValueError("supplemental discovery requires restored ownership")
        return window
    if not context.supplemental_assignments and trigger is None:
        return window
    storage = next(
        s
        for s in snapshot.current_storage_states
        if s.execution_scope_id
        == next(
            a.execution_scope_id
            for a in context.assignments
            if a.assignment_id == window.assignment_id
        )
    )
    pending = tuple(
        a
        for a in context.supplemental_assignments
        if a.execution_scope_id == storage.execution_scope_id
        and a.completed_at is None
        and a.required_by > snapshot.captured_at
    )
    runs: list[list[int]] = []
    for n, (intent, energy) in enumerate(
        zip(window.schedule.intervals, window.projection.intervals, strict=True)
    ):
        main = any(
            s.starts_at < intent.ends_at and intent.starts_at < s.ends_at
            for s in window.main_segments
        ) or any(
            r.segment.starts_at < intent.ends_at and intent.starts_at < r.segment.ends_at
            for r in window.retained_main_segments
        )
        if main or intent.intent not in {
            DailyStorageIntent.NOM,
            DailyStorageIntent.GRID_REQUIREMENT,
        }:
            continue
        if (
            not runs
            or runs[-1][-1] != n - 1
            or (
                (
                    window.projection.intervals[n - 1].storage_energy_at_end_wh
                    > window.projection.intervals[n - 1].storage_energy_at_start_wh
                )
                != (energy.storage_energy_at_end_wh > energy.storage_energy_at_start_wh)
            )
        ):
            runs.append([])
        runs[-1].append(n)
    goals = []
    used: set[int] = set()
    for old in pending:
        found = False
        for k, run in enumerate(runs):
            if k in used:
                continue
            first = window.projection.intervals[run[0]]
            last = window.projection.intervals[run[-1]]
            hit = next(
                (
                    i.ends_at
                    for n in run
                    if (
                        (i := window.projection.intervals[n]).ends_at <= old.required_by
                        and i.storage_energy_at_end_wh + 1e-6
                        >= old.target_soc * storage.usable_capacity_wh
                    )
                ),
                None,
            )
            if hit is None or first.starts_at >= old.required_by:
                continue
            # Keep the identity/target/latest energy time; only the route is revised.
            goals.append(
                replace(old, starts_at=first.starts_at, ends_at=hit, plan_id="", segment_ids=())
            )
            used.add(k)
            found = True
            break
        if not found:
            return None
    if trigger is not None:
        for k, run in enumerate(runs):
            if k in used:
                continue
            first = window.projection.intervals[run[0]]
            last = window.projection.intervals[run[-1]]
            if last.ends_at > trigger.next_starts_at or (
                last.storage_energy_at_end_wh <= first.storage_energy_at_start_wh + 1e-6
            ):
                continue
            due = next(
                (
                    i.starts_at
                    for i in trigger.deficits
                    if i.deficit_wh > 1e-6 and i.starts_at >= last.ends_at
                ),
                trigger.next_starts_at,
            )
            identity = (
                "supplemental:"
                + sha256(
                    repr(
                        (
                            window.assignment_id,
                            window.schedule.schedule_id,
                            first.starts_at,
                            last.ends_at,
                        )
                    ).encode()
                ).hexdigest()[:20]
            )
            goals.append(
                SupplementalChargeAssignment(
                    identity,
                    window.assignment_id,
                    storage.execution_scope_id,
                    min(1.0, last.storage_energy_at_end_wh / storage.usable_capacity_wh),
                    first.starts_at,
                    last.ends_at,
                    due,
                )
            )
    return replace(window, supplemental_assignments=tuple(goals))
