"""Observe HEMS outcomes without introducing device knowledge or control authority."""

from collections.abc import Callable
from typing import Protocol

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.recovery_messages import recovery_message


class HealthObserver(Protocol):
    def observe(
        self, key: str, active: bool, message: str, *, severity: str = "warning",
        fingerprint: str | None = None,
    ) -> None: ...


def observe_execution(
    notifier: HealthObserver, *, status: str, reason: str | None,
    failure_reason: str | None = None,
) -> None:
    """Only confirmed execution outcomes clear earlier execution incidents."""
    if status in {"blocked", "not_dispatched"} and failure_reason in {
        "manual_override_active", "bms_soc_calibration_active",
        "committed_segment_not_due", "historical_main_completed_waiting_for_reconciliation",
        "daily_main_execution_awaits_valid_planning", "current_execution_proof_expired_or_replaced",
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
    continuity = getattr(run.evaluation, "execution_continuity", None)
    unresolved = continuity is not None and not continuity.blocking_reasons
    notifier.observe(
        "planning_fallback", fallback,
        (recovery_message(run.evaluation.reason)
         or f"Planning in terugvalmodus: {run.evaluation.reason}")
        if fallback else ("Terugval beeindigd; het toekomstige plan is nog niet opgelost."
                          if unresolved
                          else "Planning hersteld: een berekend plan is beschikbaar."),
        fingerprint=run.evaluation.reason if fallback else None,
    )
    if not fallback:
        notifier.observe(
            "planning_unresolved", unresolved,
            ((recovery_message(run.evaluation.reason) or run.evaluation.reason)
             + f" Controle geldig tot {continuity.valid_until.isoformat()}.")
            if unresolved and continuity is not None
            else "De eerder onopgeloste planning is opnieuw beoordeeld.",
            fingerprint=run.evaluation.reason if unresolved else None,
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
