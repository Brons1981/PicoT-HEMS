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
