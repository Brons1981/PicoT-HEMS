"""Derive persistent, human-readable planner timeline transitions.

The timeline is observation-only. It emits a new state only when the semantic
planner phase changes, so Home Assistant Recorder can preserve the transition
history without reconstructing events in Lovelace.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiagnosticsTimeline:
    previous_replan_candidate: bool = False
    previous_review_signature: tuple[object, object, object] | None = None

    def evaluate(self, event: dict[str, object]) -> dict[str, object]:
        replan = event.get("pv_deviation_replan_candidate") is True
        review_status = event.get("plan_review_status")
        outcome = event.get("plan_review_outcome")
        action = event.get("plan_review_action")
        observed_at = event.get("telemetry_updated_at")
        review_signature = (review_status, outcome, action)

        timeline_event: str | None = None
        if replan and not self.previous_replan_candidate:
            timeline_event = "replan_start"
            # A completed review may already be present on the same telemetry
            # sample as the transition. Remember that signature immediately so
            # the next unchanged sample is not emitted again as plan_kept.
            if review_status == "completed":
                self.previous_review_signature = review_signature
        elif not replan and self.previous_replan_candidate:
            timeline_event = "replan_cleared"
        elif replan and review_status == "completed":
            if review_signature != self.previous_review_signature:
                if action == "keep_current_plan":
                    timeline_event = "plan_kept"
                elif action in {"replan", "change_plan"}:
                    timeline_event = "replan_required"
                else:
                    timeline_event = "plan_review"
            self.previous_review_signature = review_signature

        if not replan:
            self.previous_review_signature = None
        self.previous_replan_candidate = replan

        if timeline_event is None:
            return {}

        return {
            "diagnostics_timeline_event": timeline_event,
            "diagnostics_timeline_observed_at": observed_at,
            "diagnostics_timeline_rolling_deviation_percent": event.get(
                "pv_rolling_deviation_percent"
            ),
            "diagnostics_timeline_evaluator_status": event.get(
                "pv_deviation_evaluator_status"
            ),
            "diagnostics_timeline_plan_review_status": review_status,
            "diagnostics_timeline_plan_review_outcome": outcome,
            "diagnostics_timeline_plan_review_action": action,
            "diagnostics_timeline_control_change_allowed": event.get(
                "plan_review_control_change_allowed"
            ),
        }
