"""Build traceable relationships between Home Assistant discovery datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _display_name(item: dict[str, Any], *fields: str) -> str | None:
    """Return the first useful human-readable name from the supplied fields."""
    for field in fields:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def build_architecture_map(
    structure: dict[str, list[dict[str, Any]]],
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Relate integrations, devices, entities and areas without guessing."""
    config_entries = structure.get("config_entries", [])
    devices = structure.get("devices", [])
    entities = structure.get("entities", [])
    areas = structure.get("areas", [])

    state_ids = {
        state.get("entity_id")
        for state in states
        if isinstance(state.get("entity_id"), str)
    }
    area_by_id = {
        area.get("area_id"): area
        for area in areas
        if isinstance(area.get("area_id"), str)
    }
    device_by_id = {
        device.get("id"): device
        for device in devices
        if isinstance(device.get("id"), str)
    }
    config_entry_by_id = {
        entry.get("entry_id"): entry
        for entry in config_entries
        if isinstance(entry.get("entry_id"), str)
    }

    entities_by_device: dict[str, list[dict[str, Any]]] = defaultdict(list)
    direct_entities_by_config_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_entities: list[dict[str, Any]] = []
    entities_without_state: list[str] = []
    disabled_entities: list[str] = []

    for entity in entities:
        entity_id = entity.get("entity_id")
        device_id = entity.get("device_id")
        config_entry_id = entity.get("config_entry_id")

        if isinstance(entity_id, str) and entity_id not in state_ids:
            entities_without_state.append(entity_id)
        if entity.get("disabled_by") is not None and isinstance(entity_id, str):
            disabled_entities.append(entity_id)

        if isinstance(device_id, str):
            entities_by_device[device_id].append(entity)
        elif isinstance(config_entry_id, str):
            direct_entities_by_config_entry[config_entry_id].append(entity)
        else:
            orphan_entities.append(entity)

    devices_by_config_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_devices: list[dict[str, Any]] = []
    for device in devices:
        config_entry_ids = device.get("config_entries")
        if not isinstance(config_entry_ids, list) or not config_entry_ids:
            orphan_devices.append(device)
            continue
        linked = False
        for config_entry_id in config_entry_ids:
            if isinstance(config_entry_id, str):
                devices_by_config_entry[config_entry_id].append(device)
                linked = True
        if not linked:
            orphan_devices.append(device)

    integration_nodes: list[dict[str, Any]] = []
    for entry in config_entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str):
            continue

        device_nodes: list[dict[str, Any]] = []
        for device in sorted(
            devices_by_config_entry.get(entry_id, []),
            key=lambda item: (_display_name(item, "name_by_user", "name", "model") or "").lower(),
        ):
            device_id = device.get("id")
            device_entities = (
                entities_by_device.get(device_id, [])
                if isinstance(device_id, str)
                else []
            )
            area_id = device.get("area_id")
            area = area_by_id.get(area_id) if isinstance(area_id, str) else None
            device_nodes.append(
                {
                    "device_id": device_id,
                    "name": _display_name(device, "name_by_user", "name", "model"),
                    "manufacturer": device.get("manufacturer"),
                    "model": device.get("model"),
                    "area_id": area_id,
                    "area_name": _display_name(area, "name") if area else None,
                    "entity_count": len(device_entities),
                    "entities": sorted(
                        device_entities,
                        key=lambda item: str(item.get("entity_id", "")),
                    ),
                }
            )

        direct_entities = sorted(
            direct_entities_by_config_entry.get(entry_id, []),
            key=lambda item: str(item.get("entity_id", "")),
        )
        integration_nodes.append(
            {
                "config_entry_id": entry_id,
                "domain": entry.get("domain"),
                "title": entry.get("title"),
                "state": entry.get("state"),
                "disabled_by": entry.get("disabled_by"),
                "device_count": len(device_nodes),
                "device_entity_count": sum(node["entity_count"] for node in device_nodes),
                "direct_entity_count": len(direct_entities),
                "devices": device_nodes,
                "direct_entities": direct_entities,
            }
        )

    unlinked_config_entry_ids = sorted(
        {
            config_entry_id
            for config_entry_id in set(devices_by_config_entry) | set(direct_entities_by_config_entry)
            if config_entry_id not in config_entry_by_id
        }
    )
    entities_with_unknown_device = sorted(
        entity.get("entity_id")
        for device_id, linked_entities in entities_by_device.items()
        if device_id not in device_by_id
        for entity in linked_entities
        if isinstance(entity.get("entity_id"), str)
    )

    domain_counts = Counter(
        str(entry.get("domain"))
        for entry in config_entries
        if entry.get("domain") is not None
    )

    summary = {
        "integration_count": len(integration_nodes),
        "integration_domain_count": len(domain_counts),
        "linked_device_count": len(devices) - len(orphan_devices),
        "orphan_device_count": len(orphan_devices),
        "entity_registry_count": len(entities),
        "entity_with_state_count": sum(
            1 for entity in entities if entity.get("entity_id") in state_ids
        ),
        "entity_without_state_count": len(entities_without_state),
        "disabled_entity_count": len(disabled_entities),
        "entity_without_device_or_integration_count": len(orphan_entities),
        "entity_with_unknown_device_count": len(entities_with_unknown_device),
        "unlinked_config_entry_reference_count": len(unlinked_config_entry_ids),
        "integration_domains": dict(sorted(domain_counts.items())),
    }

    return {
        "metadata": {
            "schema": "picot_hems.discovery.architecture_map",
            "schema_version": "0.1.0",
        },
        "summary": summary,
        "integrations": sorted(
            integration_nodes,
            key=lambda item: (
                str(item.get("domain") or ""),
                str(item.get("title") or ""),
            ),
        ),
        "exceptions": {
            "orphan_devices": orphan_devices,
            "orphan_entities": orphan_entities,
            "entities_without_state": sorted(entities_without_state),
            "disabled_entities": sorted(disabled_entities),
            "entities_with_unknown_device": entities_with_unknown_device,
            "unlinked_config_entry_ids": unlinked_config_entry_ids,
        },
    }
