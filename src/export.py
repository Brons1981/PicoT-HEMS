"""Export functions for PicoT Discovery outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    """Write UTF-8 JSON in a stable, human-readable form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _contains_any_term(value: Any, terms: tuple[str, ...]) -> bool:
    """Return whether a JSON-compatible value contains one of the terms."""
    if isinstance(value, dict):
        return any(
            _contains_any_term(key, terms) or _contains_any_term(item, terms)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_any_term(item, terms) for item in value)
    if value is None:
        return False
    text = str(value).casefold()
    return any(term in text for term in terms)


def _as_id_set(value: Any) -> set[str]:
    """Normalize a scalar or collection of identifiers to a string set."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item is not None}
    return {str(value)}


def export_zendure_diagnostic(
    result: dict[str, Any], output_directory: Path
) -> Path:
    """Export all evidence related to Zendure and the @gielz integration.

    The export starts with direct textual matches and then expands through
    entity-registry, device and config-entry relationships. This keeps direct
    Zendure entities and Homey mirrors visible in one deterministic audit.
    """
    terms = ("zendure", "gielz", "solarflow", "2400pro", "2400 pro")
    structure = result["structure"]
    states = result["states"]
    entities = structure["entities"]
    devices = structure["devices"]
    config_entries = structure["config_entries"]

    matched_entity_ids: set[str] = set()
    matched_device_ids: set[str] = set()
    matched_config_entry_ids: set[str] = set()

    for state in states:
        if _contains_any_term(state, terms):
            entity_id = state.get("entity_id")
            if entity_id:
                matched_entity_ids.add(str(entity_id))

    for entity in entities:
        entity_id = entity.get("entity_id")
        if _contains_any_term(entity, terms) or (
            entity_id and str(entity_id) in matched_entity_ids
        ):
            if entity_id:
                matched_entity_ids.add(str(entity_id))
            matched_device_ids.update(_as_id_set(entity.get("device_id")))
            matched_config_entry_ids.update(
                _as_id_set(entity.get("config_entry_id"))
            )
            matched_config_entry_ids.update(
                _as_id_set(entity.get("config_entry_ids"))
            )

    for device in devices:
        device_id = device.get("id") or device.get("device_id")
        if _contains_any_term(device, terms) or (
            device_id and str(device_id) in matched_device_ids
        ):
            if device_id:
                matched_device_ids.add(str(device_id))
            matched_config_entry_ids.update(
                _as_id_set(device.get("config_entries"))
            )
            matched_config_entry_ids.update(
                _as_id_set(device.get("config_entry_id"))
            )

    for entity in entities:
        device_id = entity.get("device_id")
        config_ids = _as_id_set(entity.get("config_entry_id")) | _as_id_set(
            entity.get("config_entry_ids")
        )
        if (
            device_id and str(device_id) in matched_device_ids
        ) or config_ids.intersection(matched_config_entry_ids):
            entity_id = entity.get("entity_id")
            if entity_id:
                matched_entity_ids.add(str(entity_id))

    relevant_states = sorted(
        [
            state
            for state in states
            if str(state.get("entity_id", "")) in matched_entity_ids
        ],
        key=lambda row: str(row.get("entity_id", "")),
    )
    relevant_entities = sorted(
        [
            entity
            for entity in entities
            if str(entity.get("entity_id", "")) in matched_entity_ids
        ],
        key=lambda row: str(row.get("entity_id", "")),
    )
    relevant_devices = sorted(
        [
            device
            for device in devices
            if str(device.get("id") or device.get("device_id") or "")
            in matched_device_ids
        ],
        key=lambda row: str(row.get("id") or row.get("device_id") or ""),
    )
    relevant_config_entries = sorted(
        [
            entry
            for entry in config_entries
            if str(entry.get("entry_id") or entry.get("config_entry_id") or "")
            in matched_config_entry_ids
            or _contains_any_term(entry, terms)
        ],
        key=lambda row: str(
            row.get("entry_id") or row.get("config_entry_id") or ""
        ),
    )

    diagnostic = {
        "metadata": {
            "schema": "picot_hems.diagnostic.zendure",
            "schema_version": "0.1.0",
            "method": "direct_term_match_then_relationship_expansion",
            "filter_terms": list(terms),
        },
        "summary": {
            "state_count": len(relevant_states),
            "entity_registry_count": len(relevant_entities),
            "device_count": len(relevant_devices),
            "config_entry_count": len(relevant_config_entries),
        },
        "states": relevant_states,
        "entity_registry": relevant_entities,
        "devices": relevant_devices,
        "config_entries": relevant_config_entries,
    }

    path = output_directory / "zendure_diagnostic.json"
    write_json(path, diagnostic)
    return path


def export_capability_semantic_validation(
    result: dict[str, Any], output_directory: Path
) -> dict[str, Path]:
    """Export complete semantic validation audit and compact summary."""
    files = {
        "audit": output_directory / "capability_semantic_validation.json",
        "summary": output_directory / "capability_semantic_validation_summary.json",
    }
    write_json(files["audit"], result)
    write_json(files["summary"], result["summary"])
    return files


def export_capability_selection(
    result: dict[str, Any], output_directory: Path
) -> dict[str, Path]:
    """Export selected mappings, full selection audit and summary."""
    files = {
        "mapping": output_directory / "capability_mapping.json",
        "audit": output_directory / "capability_selection_audit.json",
        "summary": output_directory / "capability_selection_summary.json",
    }

    mapping = {
        "metadata": result["metadata"],
        "summary": result["summary"],
        "mappings": [
            {
                "capability_id": row["capability_id"],
                "category": row["category"],
                "kind": row["kind"],
                "status": row["status"],
                "selected": row["selected"],
            }
            for row in result["mappings"]
        ],
    }
    audit = {
        "metadata": result["metadata"],
        "summary": result["summary"],
        "mappings": result["mappings"],
    }

    write_json(files["mapping"], mapping)
    write_json(files["audit"], audit)
    write_json(files["summary"], result["summary"])
    return files


def export_capability_discovery(
    result: dict[str, Any], output_directory: Path
) -> dict[str, Path]:
    """Export capability candidates and deterministic discovery statistics."""
    files = {
        "candidates": output_directory / "capability_candidates.json",
        "statistics": output_directory / "capability_statistics.json",
    }

    candidates = {
        "metadata": result["metadata"],
        "summary": result["summary"],
        "capabilities": result["capabilities"],
    }
    statistics = {
        "metadata": result["metadata"],
        "summary": result["summary"],
        "statistics": result["statistics"],
    }

    write_json(files["candidates"], candidates)
    write_json(files["statistics"], statistics)

    return files


def export_discovery_snapshot(
    result: dict[str, Any], output_directory: Path
) -> dict[str, Path]:
    """Export source datasets, relationships, analysis, readiness and snapshot."""
    files = {
        "config": output_directory / "config.json",
        "states": output_directory / "states.json",
        "services": output_directory / "services.json",
        "config_entries": output_directory / "config_entries.json",
        "devices": output_directory / "devices.json",
        "entities": output_directory / "entity_registry.json",
        "areas": output_directory / "areas.json",
        "floors": output_directory / "floors.json",
        "labels": output_directory / "labels.json",
        "websocket_statuses": output_directory / "websocket_statuses.json",
        "architecture": output_directory / "architecture_map.json",
        "architecture_summary": output_directory / "architecture_summary.json",
        "architecture_exceptions": output_directory / "architecture_exceptions.json",
        "analysis": output_directory / "architecture_analysis.json",
        "analysis_summary": output_directory / "architecture_analysis_summary.json",
        "integration_health": output_directory / "integration_health.json",
        "device_health": output_directory / "device_health.json",
        "state_only_entities": output_directory / "state_only_entities.json",
        "unlinked_entity_classification": output_directory / "unlinked_entity_classification.json",
        "readiness": output_directory / "discovery_readiness.json",
        "readiness_summary": output_directory / "discovery_readiness_summary.json",
        "readiness_issues": output_directory / "discovery_readiness_issues.json",
        "capability_readiness": output_directory / "capability_readiness.json",
        "summary": output_directory / "discovery_summary.json",
        "snapshot": output_directory / "discovery_snapshot.json",
    }

    write_json(files["config"], result["config"])
    write_json(files["states"], result["states"])
    write_json(files["services"], result["services"])

    structure = result["structure"]
    write_json(files["config_entries"], structure["config_entries"])
    write_json(files["devices"], structure["devices"])
    write_json(files["entities"], structure["entities"])
    write_json(files["areas"], structure["areas"])
    write_json(files["floors"], structure["floors"])
    write_json(files["labels"], structure["labels"])

    architecture = result["architecture"]
    write_json(files["architecture"], architecture)
    write_json(files["architecture_summary"], architecture["summary"])
    write_json(files["architecture_exceptions"], architecture["exceptions"])

    analysis = result["analysis"]
    write_json(files["analysis"], analysis)
    write_json(files["analysis_summary"], analysis["summary"])
    write_json(files["integration_health"], analysis["integration_health"])
    write_json(files["device_health"], analysis["device_health"])
    write_json(files["state_only_entities"], analysis["state_only_entities"])
    write_json(files["unlinked_entity_classification"], analysis["unlinked_entities"])

    readiness = result["readiness"]
    write_json(files["readiness"], readiness)
    write_json(files["readiness_summary"], {
        "status": readiness["status"],
        "planning_allowed": readiness["planning_allowed"],
        **readiness["summary"],
    })
    write_json(files["readiness_issues"], readiness["issues"])
    write_json(files["capability_readiness"], readiness["capabilities"])

    write_json(files["websocket_statuses"], result["websocket_statuses"])
    write_json(files["summary"], result["summary"])
    write_json(files["snapshot"], result)

    return files
