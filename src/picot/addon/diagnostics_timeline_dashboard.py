"""Publish semantic PicoT planner timeline transitions to Home Assistant.

Only real timeline transitions are posted. The entity therefore changes state
only when PicoT enters a new diagnostic phase, allowing Home Assistant Recorder
to preserve an uncluttered historical event trail.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0
ENTITY_ID = "sensor.picot_planner_timeline"


def timeline_payload(event: dict[str, object]) -> dict[str, object] | None:
    """Build the HA state payload for one semantic timeline transition."""

    timeline_event = event.get("diagnostics_timeline_event")
    if not isinstance(timeline_event, str) or not timeline_event:
        return None

    return {
        "state": timeline_event,
        "attributes": {
            "friendly_name": "PicoT planner tijdlijn",
            "icon": "mdi:timeline-clock-outline",
            "observed_at": event.get("diagnostics_timeline_observed_at"),
            "rolling_deviation_percent": event.get(
                "diagnostics_timeline_rolling_deviation_percent"
            ),
            "evaluator_status": event.get(
                "diagnostics_timeline_evaluator_status"
            ),
            "plan_review_status": event.get(
                "diagnostics_timeline_plan_review_status"
            ),
            "plan_review_outcome": event.get(
                "diagnostics_timeline_plan_review_outcome"
            ),
            "plan_review_action": event.get(
                "diagnostics_timeline_plan_review_action"
            ),
            "control_change_allowed": event.get(
                "diagnostics_timeline_control_change_allowed"
            ),
        },
    }


def publish_diagnostics_timeline_state(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish a timeline transition; do nothing when no transition occurred."""

    payload = timeline_payload(event)
    if payload is None:
        return

    request = Request(
        f"{SUPERVISOR_BASE_URL}/api/states/{ENTITY_ID}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
    status = getattr(response, "status", None)
    if not isinstance(status, int) or status not in {200, 201}:
        raise RuntimeError(
            f"Home Assistant rejected diagnostics timeline state {ENTITY_ID}: {status}."
        )
