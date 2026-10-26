"""Current-action evidence for a failed plan search (ADR-037.21).

No candidate is selected, no goal is changed, and no plan is written here.
The reference adapter owns physics; execution owns dispatch and expiry guards.
"""
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import ExecutionContinuityEvidence, PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    RECOVERY_RECHECK_DELAY,
    IndependentDailyReferenceAdapter,
)


def assess_current_execution(
    snapshot: PlanningInputSnapshot, plan: ExecutionPlan,
    conversion: StorageConversionModel, unresolved: tuple[str, ...],
    *, require_complete_route: bool = False,
) -> ExecutionContinuityEvidence | None:
    due = next((s for s in plan.segments
                if s.starts_at <= snapshot.captured_at < s.ends_at), None)
    if due is None:
        return None
    # An unbound next-day obligation changes what is required from this route.
    # Temporary approval may not silently cross that boundary after a restart/poll.
    next_goal_start = min((a.starts_at
        for a in (snapshot.daily_charge_context.assignments
                  if snapshot.daily_charge_context is not None else ())
        if a.route_plan_id is None and a.completed_at is None
        and a.starts_at > snapshot.captured_at), default=due.ends_at)
    until = min(due.ends_at, snapshot.captured_at + RECOVERY_RECHECK_DELAY, next_goal_start)
    try:
        adapter = IndependentDailyReferenceAdapter()
        issues = (adapter.committed_execution_invalidity_reasons(
            snapshot=snapshot, plan=plan, conversion_model=conversion,
        ) if require_complete_route else adapter.current_execution_invalidity_reasons(
            snapshot=snapshot, plan=plan, conversion_model=conversion, until=until,
        ))
    except (ValueError, OSError) as exc:
        issues = (str(exc) or type(exc).__name__,)
    if not require_complete_route and not all(reason.split(":", 1)[0] in {
        "supplemental_goal_unreachable", "daily_main_goal_unreachable",
        "supplemental_retirement_bridge_deficit", "market_recovery_not_proven",
        "household_bridge_unreachable", "household_reserve_unreachable",
    } for reason in unresolved):
        issues = (*issues, "planning_failure_not_eligible_for_current_continuity")
    return ExecutionContinuityEvidence(
        snapshot.snapshot_id, plan.plan_id, due.segment_id, snapshot.captured_at, until,
        unresolved, issues,
    )


def failed_plan_change_blocks_execution(
    *, has_retained_plan: bool, optional_change: bool = False,
    continuing_charge: bool = False, current_shortfall: bool = False,
) -> bool:
    """One failure decision for candidate search and replacement publication.

    Optional optimisation/continuity repair cannot erase an admitted plan.
    Protecting an already ongoing charge is a separate, physically established
    permission. Neither permission creates a plan or overrides a current shortfall.
    A future goal requiring bounded physical proof uses assess_current_execution.
    """
    return (not has_retained_plan or current_shortfall
            or not (optional_change or continuing_charge))
