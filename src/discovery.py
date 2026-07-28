"""Discovery orchestration for PicoT HEMS."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from api import HomeAssistantClient


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
    """Collect a neutral and traceable Home Assistant REST snapshot."""
    collected_at = datetime.now(timezone.utc).isoformat()
    api_status = client.check_api()
    config = client.get_config()
    states = client.get_states()
    services = client.get_services()

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
    }

    return {
        "metadata": {
            "schema": "picot_hems.discovery.rest_snapshot",
            "schema_version": "0.2.0",
            "collected_at_utc": collected_at,
        },
        "api_status": api_status,
        "config": config,
        "states": states,
        "services": services,
        "summary": summary,
    }
