from __future__ import annotations

from picot.addon.diagnostics_timeline import DiagnosticsTimeline


def _event(*, replan: bool, status: str, action: str | None = None) -> dict[str, object]:
    return {
        "telemetry_updated_at": "2026-08-10T16:00:00+02:00",
        "pv_deviation_replan_candidate": replan,
        "pv_rolling_deviation_percent": -26.0 if replan else -24.0,
        "pv_deviation_evaluator_status": (
            "persistent_under_forecast" if replan else "within_tolerance"
        ),
        "plan_review_status": status,
        "plan_review_outcome": (
            "current_plan_still_feasible" if action == "keep_current_plan" else None
        ),
        "plan_review_action": action,
        "plan_review_control_change_allowed": False,
    }


def test_timeline_emits_replan_start_once() -> None:
    timeline = DiagnosticsTimeline()

    first = timeline.evaluate(_event(replan=True, status="completed", action="keep_current_plan"))
    second = timeline.evaluate(_event(replan=True, status="completed", action="keep_current_plan"))

    assert first["diagnostics_timeline_event"] == "replan_start"
    assert second == {}


def test_timeline_emits_plan_kept_after_review_transition() -> None:
    timeline = DiagnosticsTimeline(previous_replan_candidate=True)

    result = timeline.evaluate(
        _event(replan=True, status="completed", action="keep_current_plan")
    )

    assert result["diagnostics_timeline_event"] == "plan_kept"
    assert result["diagnostics_timeline_plan_review_action"] == "keep_current_plan"


def test_timeline_emits_replan_cleared() -> None:
    timeline = DiagnosticsTimeline(previous_replan_candidate=True)

    result = timeline.evaluate(_event(replan=False, status="not_requested"))

    assert result["diagnostics_timeline_event"] == "replan_cleared"
    assert result["diagnostics_timeline_rolling_deviation_percent"] == -24.0


def test_timeline_can_emit_same_review_again_after_recovery() -> None:
    timeline = DiagnosticsTimeline(previous_replan_candidate=True)
    review = _event(replan=True, status="completed", action="keep_current_plan")

    assert timeline.evaluate(review)["diagnostics_timeline_event"] == "plan_kept"
    assert timeline.evaluate(review) == {}
    assert timeline.evaluate(_event(replan=False, status="not_requested"))[
        "diagnostics_timeline_event"
    ] == "replan_cleared"
    assert timeline.evaluate(_event(replan=True, status="completed", action="keep_current_plan"))[
        "diagnostics_timeline_event"
    ] == "replan_start"
