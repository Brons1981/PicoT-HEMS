"""Observe HEMS outcomes without introducing device knowledge or control authority."""

from collections.abc import Callable
from typing import Protocol

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.recovery_messages import recovery_message


class HealthObserver(Protocol):
    def observe(
        self, key: str, active: bool, message: str, *, severity: str = "warning",
    ) -> None: ...


def observe_execution(
    notifier: HealthObserver, *, status: str, reason: str | None,
    failure_reason: str | None = None,
) -> None:
    """Only confirmed execution outcomes clear earlier execution incidents."""
    if status in {"blocked", "not_dispatched"} and failure_reason in {
        "manual_override_active", "bms_soc_calibration_active",
        "committed_segment_not_due", "historical_main_completed_waiting_for_reconciliation",
    }:
        # Intentional ownership and clock waits are not failures, nor proof
        # that a previously failed command has recovered.
        return
    success = status in {"dispatched", "already_active"}
    failed = status in {
        "failed", "dispatch_failed", "rejected", "mode_feedback_timeout",
        "translation_failed", "translation_blocked", "blocked",
    } or (status == "not_dispatched" and bool(failure_reason))
    if success or failed:
        notifier.observe(
            "execution_failure", failed,
            (recovery_message(failure_reason or reason or status)
             or f"Batterijaansturing geblokkeerd of mislukt: {failure_reason or reason or status}")
            if failed else "Batterijaansturing hersteld.",
            severity="error",
        )
    if success:
        restricted = reason == "ev_storage_support_prohibited"
        notifier.observe(
            "excluded_load_guard", restricted,
            "Batterijregeling beperkt: uitgesloten belasting kan niet veilig worden afgetrokken."
            if restricted else "Beperking voor uitgesloten belasting opgeheven.",
        )


def observe_planning_run(notifier: HealthObserver, run: CanonicalPipelineRun) -> None:
    fallback = run.evaluation.status == "fallback_active"
    notifier.observe(
        "planning_fallback", fallback,
        (recovery_message(run.evaluation.reason)
         or f"Planning in terugvalmodus: {run.evaluation.reason}")
        if fallback else "Planning hersteld: een berekend plan is beschikbaar.",
    )
    observe_execution(
        notifier, status=run.vendor_result.status,
        reason=run.primitive_boundary.execution_reason,
        failure_reason=run.vendor_result.failure_reason,
    )


def observe_cycle[T](notifier: HealthObserver, action: Callable[[], T]) -> T:
    """Preserve exception policy; report recovery after a subsequent successful cycle."""
    try:
        result = action()
    except Exception as exc:
        notifier.observe("runtime_error", True, f"HEMS regelcyclus mislukt: {type(exc).__name__}",
                         severity="error")
        raise
    notifier.observe("runtime_error", False, "HEMS regelcyclus hersteld.", severity="error")
    return result
