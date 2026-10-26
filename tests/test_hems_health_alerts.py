from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.health_alerts import observe_cycle, observe_execution, observe_planning_run


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool, str, str]] = []

    def observe(self, key: str, active: bool, message: str, *, severity: str = "warning",
                fingerprint: str | None = None) -> None:
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
    "daily_main_execution_awaits_valid_planning", "current_execution_proof_expired_or_replaced",
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
    assert ("execution_failure", False) in [event[:2] for event in recorder.events]


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


def test_retaining_current_execution_does_not_report_complete_planning_recovery():
    recorder = Recorder()
    run = cast(CanonicalPipelineRun, SimpleNamespace(
        evaluation=SimpleNamespace(
            status="plan_retained",
            reason="planning_unresolved_current_execution_retained:"
                   "supplemental_goal_unreachable:open-goal",
            execution_continuity=SimpleNamespace(
                blocking_reasons=(), valid_until=datetime(2026, 10, 26, 13, 15, tzinfo=UTC)),
        ),
        primitive_boundary=SimpleNamespace(execution_reason="retained"),
        vendor_result=SimpleNamespace(status="already_active", failure_reason=None),
    ))
    observe_planning_run(recorder, run)
    unresolved = next(event for event in recorder.events if event[0] == "planning_unresolved")
    assert unresolved[1] is True
    assert "supplemental_goal_unreachable:open-goal" in unresolved[2]
    fallback = next(event for event in recorder.events if event[0] == "planning_fallback")
    assert fallback[1] is False
    assert "nog niet opgelost" in fallback[2]


def test_planning_incident_sequence_survives_restart_without_false_recovery(tmp_path, monkeypatch):
    import json
    from datetime import timedelta

    from picot.health_notifications import HealthNotifier

    monkeypatch.setattr(HealthNotifier, "_run", lambda self: None)
    path = tmp_path / "health.json"
    now = datetime(2026, 10, 26, 13, 0, tzinfo=UTC)

    def run(status, reason, until=None):
        return cast(CanonicalPipelineRun, SimpleNamespace(
            evaluation=SimpleNamespace(status=status, reason=reason,
                execution_continuity=SimpleNamespace(blocking_reasons=(), valid_until=until)
                                    if until is not None else None),
            primitive_boundary=SimpleNamespace(execution_reason=None),
            vendor_result=SimpleNamespace(status="already_active", failure_reason=None),
        ))

    fallback = run("fallback_active", "daily_main_planning_data_unavailable:price_points")
    unresolved = run("plan_retained", "planning_unresolved_current_execution_retained:"
                     "supplemental_goal_unreachable:goal", now + timedelta(minutes=15))
    first = HealthNotifier("token", "HEMS", path)
    observe_planning_run(first, fallback)
    observe_planning_run(first, fallback)
    observe_planning_run(first, unresolved)
    first.close()
    restarted = HealthNotifier("token", "HEMS", path)
    observe_planning_run(restarted, unresolved)
    observe_planning_run(restarted, run("plan_retained", unresolved.evaluation.reason,
                                       now + timedelta(minutes=30)))
    assert len(json.loads(path.read_text())["pending"]) == 3
    observe_planning_run(restarted, run("fallback_active",
        "daily_main_planning_data_unavailable:pv_energy_timeline"))
    saved = json.loads(path.read_text())
    assert saved["active"]["planning_unresolved"] is True
    assert len(saved["pending"]) == 4
    assert not any("Planning hersteld" in event["message"] for event in saved["pending"])
    observe_planning_run(restarted, run("winner_selected", "valid_route"))
    restarted.close()
    pending = json.loads(path.read_text())["pending"]
    assert [(e["key"], e["active"]) for e in pending] == [
        ("planning_fallback", True), ("planning_fallback", False),
        ("planning_unresolved", True), ("planning_fallback", True),
        ("planning_fallback", False), ("planning_unresolved", False)]
    assert "nog niet opgelost" in pending[1]["message"]
    assert "Planning hersteld" in pending[-2]["message"]
