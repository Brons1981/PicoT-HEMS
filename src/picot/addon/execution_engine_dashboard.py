"""Publish observer-only live ExecutionEngine evidence to Home Assistant."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0


def execution_engine_dashboard_state(event: dict[str, object]) -> dict[str, object]:
    """Build one dedicated execution observer sensor."""

    return {
        "state": event.get("execution_engine_status", "unknown"),
        "attributes": {
            "friendly_name": "PicoT execution engine observer",
            "icon": "mdi:cog-transfer-outline",
            "observer_only": True,
            "captured_at": event.get("captured_at"),
            "snapshot_id": event.get("snapshot_id"),
            "execution_plan_set_id": event.get("execution_plan_set_id"),
            "execution_engine_observed": event.get("execution_engine_observed", False),
            "execution_fallback_policy_resolved": event.get(
                "execution_fallback_policy_resolved", False
            ),
            "execution_request_count": event.get("execution_request_count", 0),
            "execution_record_count": event.get("execution_record_count", 0),
            "execution_approved_count": event.get("execution_approved_count", 0),
            "execution_replan_required_count": event.get(
                "execution_replan_required_count", 0
            ),
            "execution_rejected_count": event.get("execution_rejected_count", 0),
            "execution_cancelled_count": event.get("execution_cancelled_count", 0),
            "execution_engine_error": event.get("execution_engine_error"),
        },
    }


def publish_execution_engine_state(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish the execution observer sensor through the HA REST API."""

    request = Request(
        f"{SUPERVISOR_BASE_URL}/api/states/sensor.picot_execution_engine_observer",
        data=json.dumps(
            execution_engine_dashboard_state(event), separators=(",", ":")
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
    status = getattr(response, "status", None)
    if not isinstance(status, int) or status not in {200, 201}:
        raise RuntimeError(f"Home Assistant rejected execution observer state: {status}.")
