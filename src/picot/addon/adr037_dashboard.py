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
        "current_storage_soc": event.get("current_storage_soc"),
        "current_storage_energy_wh": event.get("current_storage_energy_wh"),
        "live_storage_min_soc_percent": event.get("live_storage_min_soc_percent"),
        "live_storage_max_soc_percent": event.get("live_storage_max_soc_percent"),
        "live_storage_operating_window_wh": event.get("live_storage_operating_window_wh"),
        "effective_storage_max_soc": event.get("effective_storage_max_soc"),
        "effective_storage_max_energy_wh": event.get("effective_storage_max_energy_wh"),
        "zendure_available_energy": event.get("zendure_available_energy"),
        "zendure_required_energy": event.get("zendure_required_energy"),
        "zendure_remaining_discharge_time": event.get("zendure_remaining_discharge_time"),
        "zendure_remaining_charge_time": event.get("zendure_remaining_charge_time"),
        "zendure_configured_discharge_power_w": event.get(
            "zendure_configured_discharge_power_w"
        ),
        "zendure_configured_charge_power_w": event.get(
            "zendure_configured_charge_power_w"
        ),
        "flow_observer_status": event.get("flow_observer_status"),
        "flow_observer_raw_mismatch": event.get("flow_observer_raw_mismatch"),
        "flow_observer_persistent_mismatch": event.get(
            "flow_observer_persistent_mismatch"
        ),
        "flow_observer_consecutive_samples": event.get(
            "flow_observer_consecutive_samples"
        ),
        "flow_observer_required_samples": event.get("flow_observer_required_samples"),
        "flow_observer_recommendation": event.get("flow_observer_recommendation"),
        "flow_observer_grid_export_w": event.get("flow_observer_grid_export_w"),
        "flow_observer_battery_discharge_w": event.get(
            "flow_observer_battery_discharge_w"
        ),
        "flow_observer_pv_power_w": event.get("flow_observer_pv_power_w"),
        "evidence_confidence_decision": event.get("evidence_confidence_decision"),
        "canonical_price_opportunity_count": event.get(
            "canonical_price_opportunity_count"
        ),
        "price_window_context": event.get("price_window_context"),
        "price_window_starts_at": event.get("price_window_starts_at"),
        "price_window_ends_at": event.get("price_window_ends_at"),
        "price_window_best_later_starts_at": event.get(
            "price_window_best_later_starts_at"
        ),
        "price_window_best_later_price_eur_per_kwh": event.get(
            "price_window_best_later_price_eur_per_kwh"
        ),
        "requirement_energy_wh": event.get("adr037_requirement_energy_wh"),
        "requirement_required_by": event.get("adr037_requirement_required_by"),
        "remaining_charge_energy_wh": event.get("adr037_remaining_charge_energy_wh"),
        "latest_full_power_charge_start": event.get(
            "adr037_latest_full_power_charge_start"
        ),
        "recovery_start_due": event.get("adr037_recovery_start_due"),
        "technically_recoverable": event.get("adr037_technically_recoverable"),
        "charge_needed_now": event.get("adr037_charge_needed_now"),
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
