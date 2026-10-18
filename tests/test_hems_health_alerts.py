from types import SimpleNamespace
from typing import cast

import pytest

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.health_alerts import observe_cycle, observe_execution, observe_planning_run


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool, str, str]] = []

    def observe(self, key: str, active: bool, message: str, *, severity: str = "warning") -> None:
        self.events.append((key, active, message, severity))


@pytest.mark.parametrize(
    "status", ["failed", "dispatch_failed", "blocked", "mode_feedback_timeout"],
)
def test_execution_failure_is_reported_and_only_confirmed_success_clears(status: str) -> None:
    recorder = Recorder()
    observe_execution(recorder, status=status, reason=None, failure_reason="unavailable")
    assert recorder.events[-1][:2] == ("execution_failure", True)
    count = len(recorder.events)
    for pending in ("not_due", "observer_only", "awaiting_feedback"):
        observe_execution(recorder, status=pending, reason=None)
    assert len(recorder.events) == count
    observe_execution(recorder, status="already_active", reason="normal")
    assert ("execution_failure", False) in [event[:2] for event in recorder.events]


def test_guard_reports_actual_applied_boundary_and_recovers() -> None:
    recorder = Recorder()
    observe_execution(recorder, status="dispatched", reason="ev_storage_support_prohibited")
    assert recorder.events[-1][:2] == ("excluded_load_guard", True)
    observe_execution(recorder, status="blocked", reason=None, failure_reason="missing_data")
    assert recorder.events[-1][:2] == ("execution_failure", True)
    observe_execution(
        recorder, status="already_active", reason="active canonical MEP segment boundary",
    )
    assert recorder.events[-1][:2] == ("excluded_load_guard", False)


@pytest.mark.parametrize("reason", [
    "manual_override_active", "bms_soc_calibration_active", "committed_segment_not_due",
    "historical_main_completed_waiting_for_reconciliation",
])
def test_intentional_execution_hold_is_neither_failure_nor_recovery(reason: str) -> None:
    recorder = Recorder()
    observe_execution(recorder, status="blocked", reason=None, failure_reason=reason)
    assert recorder.events == []


def test_missing_manual_ownership_evidence_still_reports_real_blocker() -> None:
    recorder = Recorder()
    observe_execution(recorder, status="blocked", reason=None,
                      failure_reason="manual_override_provenance_unverified")
    assert recorder.events[-1][:2] == ("execution_failure", True)


def test_planning_and_execution_are_independent_incidents() -> None:
    recorder = Recorder()
    run = cast(CanonicalPipelineRun, SimpleNamespace(
        evaluation=SimpleNamespace(status="fallback_active", reason="no_feasible_plan"),
        primitive_boundary=SimpleNamespace(execution_reason="fallback"),
        vendor_result=SimpleNamespace(status="already_active", failure_reason=None),
    ))
    observe_planning_run(recorder, run)
    assert recorder.events[0][:2] == ("planning_fallback", True)
    assert "no_feasible_plan" in recorder.events[0][2]
    assert recorder.events[1][:2] == ("execution_failure", False)


def test_cycle_reports_exception_without_changing_exception_policy() -> None:
    recorder = Recorder()

    def fail() -> None:
        raise RuntimeError("private response details")

    with pytest.raises(RuntimeError, match="private response details"):
        observe_cycle(recorder, fail)
    assert recorder.events[-1][:2] == ("runtime_error", True)
    assert "private response" not in recorder.events[-1][2]
    assert observe_cycle(recorder, lambda: "unchanged") == "unchanged"
    assert recorder.events[-1][:2] == ("runtime_error", False)
