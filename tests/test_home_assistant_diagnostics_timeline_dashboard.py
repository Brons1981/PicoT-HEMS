from __future__ import annotations

from picot.addon.diagnostics_timeline_dashboard import timeline_payload


def test_timeline_payload_exposes_semantic_transition_and_evidence() -> None:
    event: dict[str, object] = {
        "diagnostics_timeline_event": "replan_start",
        "diagnostics_timeline_observed_at": "2026-08-10T15:56:48+02:00",
        "diagnostics_timeline_rolling_deviation_percent": -25.13,
        "diagnostics_timeline_evaluator_status": "persistent_under_forecast",
        "diagnostics_timeline_plan_review_status": "completed",
        "diagnostics_timeline_plan_review_outcome": "current_plan_still_feasible",
        "diagnostics_timeline_plan_review_action": "keep_current_plan",
        "diagnostics_timeline_control_change_allowed": False,
    }

    payload = timeline_payload(event)

    assert payload is not None
    assert payload["state"] == "replan_start"
    attributes = payload["attributes"]
    assert isinstance(attributes, dict)
    assert attributes["rolling_deviation_percent"] == -25.13
    assert attributes["plan_review_action"] == "keep_current_plan"
    assert attributes["control_change_allowed"] is False


def test_timeline_payload_skips_unchanged_samples() -> None:
    assert timeline_payload({}) is None
