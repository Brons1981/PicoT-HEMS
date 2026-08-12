"""Publish live ADR-037 observer status as a Home Assistant sensor."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0

DashboardPayload = dict[str, object]
DashboardStates = dict[str, DashboardPayload]


def adr037_dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build one read-only sensor for the live ADR-037 observer pipeline."""

    ready = event.get("adr037_live_ready")
    state = "ready" if ready is True else "blocked"
    if ready is None:
        state = "unknown"
    attributes: dict[str, object] = {
        "friendly_name": "PicoT ADR-037 observer",
        "icon": "mdi:clipboard-text-search-outline",
        "observer_only": event.get("observer_only", True),
        "control_change_allowed": event.get("control_change_allowed", False),
        "captured_at": event.get("captured_at"),
        "snapshot_id": event.get("snapshot_id"),
        "pipeline_stage": event.get("adr037_pipeline_stage_reached"),
        "blockers": event.get("adr037_live_blockers", []),
        "projected_balance_confidence": event.get("projected_balance_confidence"),
        "storage_capability_available": event.get("storage_capability_available"),
        "storage_max_charge_power_w": event.get("storage_max_charge_power_w"),
        "effective_storage_max_soc": event.get("effective_storage_max_soc"),
        "evidence_confidence_decision": event.get("evidence_confidence_decision"),
        "canonical_price_opportunity_count": event.get(
            "canonical_price_opportunity_count"
        ),
        "requirement_energy_wh": event.get("adr037_requirement_energy_wh"),
        "pv_only_sufficient": event.get("adr037_pv_only_sufficient"),
        "candidate_count": event.get("adr037_candidate_count"),
        "evaluation_status": event.get("adr037_evaluation_status"),
        "winning_candidate_id": event.get("adr037_winning_candidate_id"),
        "winning_candidate_family": event.get("adr037_winning_candidate_family"),
    }
    return {
        "sensor.picot_adr037_observer": {
            "state": state,
            "attributes": attributes,
        }
    }


def publish_adr037_dashboard_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish the observer sensor through the Home Assistant REST API."""

    for entity_id, payload in adr037_dashboard_states(event).items():
        request = Request(
            f"{SUPERVISOR_BASE_URL}/api/states/{entity_id}",
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
                f"Home Assistant rejected ADR-037 dashboard state {entity_id}: {status}."
            )
