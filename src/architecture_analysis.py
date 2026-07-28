"""Deterministic structural analysis for PicoT Home Assistant Discovery."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


VIRTUAL_DOMAIN_GROUPS: dict[str, set[str]] = {
    "automation": {"automation", "script", "scene"},
    "helper": {
        "counter", "input_boolean", "input_button", "input_datetime",
        "input_number", "input_select", "input_text", "schedule", "timer",
    },
    "person_location": {"device_tracker", "person", "zone"},
    "system": {"event", "persistent_notification", "sun", "update"},
    "weather_forecast": {"weather"},
}


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else "unknown"


def _classify_unlinked(entity: dict[str, Any]) -> str:
    entity_id = entity.get("entity_id")
    domain = _domain(entity_id) if isinstance(entity_id, str) else "unknown"
    for category, domains in VIRTUAL_DOMAIN_GROUPS.items():
        if domain in domains:
            return category
    return "unclassified"


def _status_from_counts(
    *, total: int, unavailable: int, missing_state: int, disabled: bool = False
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if disabled:
        reasons.append("disabled")
    if total == 0:
        reasons.append("no_entities")
    if unavailable:
        reasons.append("unavailable_entities")
    if missing_state:
        reasons.append("entities_without_current_state")

    if disabled:
        return "disabled", reasons
    if total == 0:
        return "empty", reasons
    if unavailable or missing_state:
        return "attention", reasons
    return "ok", reasons


def analyze_architecture(
    architecture: dict[str, Any],
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze architecture relationships using only observed Home Assistant data."""
    state_by_id = {
        state["entity_id"]: state
        for state in states
        if isinstance(state.get("entity_id"), str)
    }

    registry_entity_ids: set[str] = set()
    unlinked_classified: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()

    for entity in architecture.get("exceptions", {}).get("orphan_entities", []):
        entity_id = entity.get("entity_id")
        category = _classify_unlinked(entity)
        category_counts[category] += 1
        unlinked_classified.append(
            {
                "entity_id": entity_id,
                "domain": _domain(entity_id) if isinstance(entity_id, str) else None,
                "category": category,
                "disabled_by": entity.get("disabled_by"),
                "has_current_state": entity_id in state_by_id,
            }
        )

    integration_health: list[dict[str, Any]] = []
    device_health: list[dict[str, Any]] = []

    for integration in architecture.get("integrations", []):
        integration_entity_ids: list[str] = []
        integration_unavailable = 0
        integration_missing_state = 0

        for device in integration.get("devices", []):
            ids = [
                entity.get("entity_id")
                for entity in device.get("entities", [])
                if isinstance(entity.get("entity_id"), str)
            ]
            registry_entity_ids.update(ids)
            unavailable = sum(
                1 for entity_id in ids if state_by_id.get(entity_id, {}).get("state") == "unavailable"
            )
            missing_state = sum(1 for entity_id in ids if entity_id not in state_by_id)
            status, reasons = _status_from_counts(
                total=len(ids), unavailable=unavailable, missing_state=missing_state
            )
            device_health.append(
                {
                    "device_id": device.get("device_id"),
                    "name": device.get("name"),
                    "config_entry_id": integration.get("config_entry_id"),
                    "integration_domain": integration.get("domain"),
                    "entity_count": len(ids),
                    "unavailable_entity_count": unavailable,
                    "entity_without_state_count": missing_state,
                    "structural_status": status,
                    "reasons": reasons,
                }
            )
            integration_entity_ids.extend(ids)
            integration_unavailable += unavailable
            integration_missing_state += missing_state

        direct_ids = [
            entity.get("entity_id")
            for entity in integration.get("direct_entities", [])
            if isinstance(entity.get("entity_id"), str)
        ]
        registry_entity_ids.update(direct_ids)
        integration_entity_ids.extend(direct_ids)
        integration_unavailable += sum(
            1 for entity_id in direct_ids if state_by_id.get(entity_id, {}).get("state") == "unavailable"
        )
        integration_missing_state += sum(
            1 for entity_id in direct_ids if entity_id not in state_by_id
        )

        status, reasons = _status_from_counts(
            total=len(integration_entity_ids),
            unavailable=integration_unavailable,
            missing_state=integration_missing_state,
            disabled=integration.get("disabled_by") is not None,
        )
        integration_health.append(
            {
                "config_entry_id": integration.get("config_entry_id"),
                "domain": integration.get("domain"),
                "title": integration.get("title"),
                "config_entry_state": integration.get("state"),
                "device_count": integration.get("device_count", 0),
                "entity_count": len(integration_entity_ids),
                "unavailable_entity_count": integration_unavailable,
                "entity_without_state_count": integration_missing_state,
                "structural_status": status,
                "reasons": reasons,
            }
        )

    for entity in architecture.get("exceptions", {}).get("orphan_entities", []):
        entity_id = entity.get("entity_id")
        if isinstance(entity_id, str):
            registry_entity_ids.add(entity_id)

    state_only_entities = sorted(set(state_by_id) - registry_entity_ids)
    integration_status_counts = Counter(item["structural_status"] for item in integration_health)
    device_status_counts = Counter(item["structural_status"] for item in device_health)

    return {
        "metadata": {
            "schema": "picot_hems.discovery.architecture_analysis",
            "schema_version": "0.1.0",
            "status_scope": "structural_only",
        },
        "summary": {
            "state_only_entity_count": len(state_only_entities),
            "unlinked_entity_count": len(unlinked_classified),
            "unlinked_entity_categories": dict(sorted(category_counts.items())),
            "integration_status_counts": dict(sorted(integration_status_counts.items())),
            "device_status_counts": dict(sorted(device_status_counts.items())),
        },
        "state_only_entities": state_only_entities,
        "unlinked_entities": sorted(
            unlinked_classified, key=lambda item: str(item.get("entity_id") or "")
        ),
        "integration_health": sorted(
            integration_health,
            key=lambda item: (str(item.get("domain") or ""), str(item.get("title") or "")),
        ),
        "device_health": sorted(
            device_health,
            key=lambda item: (str(item.get("integration_domain") or ""), str(item.get("name") or "")),
        ),
    }
