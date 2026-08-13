"""Publish observer-only PicoT runtime performance timings to Home Assistant."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0

PERFORMANCE_FIELDS = (
    "runtime_perf_base_evidence_ms",
    "runtime_perf_flow_observer_ms",
    "runtime_perf_canonical_pv_deviation_ms",
    "runtime_perf_snapshot_build_ms",
    "runtime_perf_actual_pv_integration_ms",
    "runtime_perf_price_fetch_ms",
    "runtime_perf_adr037_planner_ms",
    "runtime_perf_tab001_mode_control_ms",
    "runtime_perf_total_composed_cycle_ms",
)


def runtime_performance_state(event: dict[str, object]) -> dict[str, object]:
    """Build one diagnostics-only sensor from already-measured stage timings."""

    attributes: dict[str, object] = {
        "friendly_name": "PicoT runtime performance",
        "icon": "mdi:speedometer",
        "observer_only": True,
        "captured_at": event.get("captured_at"),
        "snapshot_id": event.get("snapshot_id"),
    }
    for field in PERFORMANCE_FIELDS:
        attributes[field.removeprefix("runtime_perf_")] = event.get(field)
    return {
        "state": event.get("runtime_perf_total_composed_cycle_ms", "unknown"),
        "attributes": attributes,
    }


def publish_runtime_performance_state(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish diagnostics-only runtime timing evidence through HA REST."""

    payload = runtime_performance_state(event)
    request = Request(
        f"{SUPERVISOR_BASE_URL}/api/states/sensor.picot_runtime_performance",
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
            f"Home Assistant rejected runtime performance state: {status}."
        )
