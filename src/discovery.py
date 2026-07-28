"""Discovery orchestration for PicoT HEMS."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from api import HomeAssistantClient
from architecture import build_architecture_map
from websocket_api import HomeAssistantWebSocketClient


def _count_services(services: list[dict[str, Any]]) -> int:
    """Count individual services across all Home Assistant domains."""
    total = 0
    for domain in services:
        domain_services = domain.get("services", {})
        if isinstance(domain_services, dict):
            total += len(domain_services)
    return total


def _count_entity_domains(states: list[dict[str, Any]]) -> dict[str, int]:
    """Count entities per Home Assistant domain."""
    counter: Counter[str] = Counter()
    for state in states:
        entity_id = state.get("entity_id")
        if isinstance(entity_id, str) and "." in entity_id:
            counter[entity_id.split(".", 1)[0]] += 1
    return dict(sorted(counter.items()))


def run_discovery(client: HomeAssistantClient) -> dict[str, Any]:
    """Collect REST data, registries and their traceable relationships."""
    collected_at = datetime.now(timezone.utc).isoformat()
    api_status = client.check_api()
    config = client.get_config()
    states = client.get_states()
    services = client.get_services()

    websocket_client = HomeAssistantWebSocketClient(
        base_url=client.base_url,
        token=client.token,
        timeout_seconds=client.timeout_seconds,
    )
    structure = websocket_client.collect_structure()
    datasets = structure["datasets"]
    statuses = structure["statuses"]
    architecture = build_architecture_map(datasets, states)

    summary = {
        "collected_at_utc": collected_at,
        "home_assistant_version": config.get("version"),
        "location_name": config.get("location_name"),
        "time_zone": config.get("time_zone"),
        "state_count": len(states),
        "entity_domain_count": len(_count_entity_domains(states)),
        "service_domain_count": len(services),
        "service_count": _count_services(services),
        "entity_domains": _count_entity_domains(states),
        "config_entry_count": len(datasets["config_entries"]),
        "device_count": len(datasets["devices"]),
        "entity_registry_count": len(datasets["entities"]),
        "area_count": len(datasets["areas"]),
        "floor_count": len(datasets["floors"]),
        "label_count": len(datasets["labels"]),
        "websocket_statuses": statuses,
        "architecture": architecture["summary"],
    }

    return {
        "metadata": {
            "schema": "picot_hems.discovery.architectural_snapshot",
            "schema_version": "0.4.0",
            "collected_at_utc": collected_at,
        },
        "api_status": api_status,
        "config": config,
        "states": states,
        "services": services,
        "structure": datasets,
        "architecture": architecture,
        "websocket_statuses": statuses,
        "summary": summary,
    }
