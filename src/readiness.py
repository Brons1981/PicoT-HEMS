"""Deterministic relevance, severity and readiness analysis for PicoT Discovery."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


ENERGY_DEVICE_CLASSES = {
    "battery", "current", "energy", "energy_storage", "frequency", "power",
    "power_factor", "voltage",
}
PLANNING_DEVICE_CLASSES = ENERGY_DEVICE_CLASSES | {
    "atmospheric_pressure", "duration", "illuminance", "temperature", "timestamp",
}
LOW_RELEVANCE_DOMAINS = {
    "automation", "button", "counter", "event", "input_boolean", "input_button",
    "input_datetime", "input_number", "input_select", "input_text", "scene", "script",
    "select", "sun", "timer", "update", "zone",
}
MEDIUM_RELEVANCE_DOMAINS = {
    "binary_sensor", "climate", "cover", "fan", "light", "lock", "number", "switch",
    "weather",
}


def _domain(entity_id: str | None) -> str:
    if isinstance(entity_id, str) and "." in entity_id:
        return entity_id.split(".", 1)[0]
    return "unknown"


def _entity_characteristics(
    entity: dict[str, Any], state: dict[str, Any] | None
) -> dict[str, Any]:
    attributes = state.get("attributes", {}) if isinstance(state, dict) else {}
    if not isinstance(attributes, dict):
        attributes = {}
    device_class = entity.get("device_class") or attributes.get("device_class")
    state_class = entity.get("state_class") or attributes.get("state_class")
    entity_id = entity.get("entity_id")
    return {
        "domain": _domain(entity_id if isinstance(entity_id, str) else None),
        "device_class": device_class,
        "state_class": state_class,
        "entity_category": entity.get("entity_category"),
        "disabled": entity.get("disabled_by") is not None,
    }


def _relevance(characteristics: dict[str, Any]) -> tuple[str, list[str]]:
    domain = characteristics["domain"]
    device_class = characteristics["device_class"]
    entity_category = characteristics["entity_category"]

    if entity_category in {"diagnostic", "config"}:
        return "low", ["diagnostic_or_config_entity"]
    if device_class in ENERGY_DEVICE_CLASSES:
        return "very_high", ["energy_device_class"]
    if domain == "sensor" and device_class in PLANNING_DEVICE_CLASSES:
        return "high", ["planning_device_class"]
    if domain in LOW_RELEVANCE_DOMAINS:
        return "low", ["low_relevance_domain"]
    if domain in MEDIUM_RELEVANCE_DOMAINS:
        return "medium", ["operational_domain"]
    if domain == "sensor":
        return "medium", ["generic_sensor"]
    return "unknown", ["no_relevance_rule_matched"]


def _severity(
    *, issue_type: str, relevance: str, disabled: bool, required: bool
) -> tuple[str, list[str]]:
    """Classify impact without treating relevance as a dependency declaration."""
    if disabled:
        return "informational", ["entity_disabled"]
    if issue_type == "state_only":
        return "informational", ["state_exists_without_registry_entry"]
    if required:
        return "critical", ["explicit_required_dependency_unavailable"]
    if relevance in {"very_high", "high"}:
        return "warning", ["relevant_but_not_declared_required"]
    if relevance == "medium":
        return "warning", ["operational_data_unavailable"]
    return "informational", ["low_or_unknown_relevance"]


def _capabilities(characteristics: dict[str, Any]) -> list[str]:
    domain = characteristics["domain"]
    device_class = characteristics["device_class"]
    capabilities: list[str] = []
    if device_class in ENERGY_DEVICE_CLASSES:
        capabilities.append("energy_observation")
    if device_class == "battery":
        capabilities.append("battery_state_observation")
    if domain == "weather" or device_class in {
        "atmospheric_pressure", "illuminance", "temperature",
    }:
        capabilities.append("forecast_context")
    if domain in {"switch", "number", "select", "button", "climate", "cover"}:
        capabilities.append("device_control")
    return sorted(set(capabilities))


def analyze_readiness(
    structure: dict[str, list[dict[str, Any]]],
    states: list[dict[str, Any]],
    architecture: dict[str, Any],
    analysis: dict[str, Any],
    websocket_statuses: dict[str, dict[str, Any]],
    required_entity_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Create readiness from observations and explicit dependency declarations.

    An entity's relevance never makes it mandatory by itself. Only entity IDs supplied
    through ``required_entity_ids`` may block planning. Discovery currently supplies no
    required IDs; role assignment belongs to the later Capability Layer.
    """
    required_entity_ids = required_entity_ids or set()
    state_by_id = {
        state["entity_id"]: state
        for state in states
        if isinstance(state.get("entity_id"), str)
    }
    registry_by_id = {
        entity["entity_id"]: entity
        for entity in structure.get("entities", [])
        if isinstance(entity.get("entity_id"), str)
    }

    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_issue(entity_id: str, issue_type: str) -> None:
        key = (entity_id, issue_type)
        if key in seen:
            return
        seen.add(key)
        entity = registry_by_id.get(entity_id, {"entity_id": entity_id})
        state = state_by_id.get(entity_id)
        characteristics = _entity_characteristics(entity, state)
        relevance, relevance_reasons = _relevance(characteristics)
        required = entity_id in required_entity_ids
        severity, severity_reasons = _severity(
            issue_type=issue_type,
            relevance=relevance,
            disabled=characteristics["disabled"],
            required=required,
        )
        issues.append(
            {
                "issue_id": f"{issue_type}:{entity_id}",
                "issue_type": issue_type,
                "entity_id": entity_id,
                "domain": characteristics["domain"],
                "device_class": characteristics["device_class"],
                "state_class": characteristics["state_class"],
                "entity_category": characteristics["entity_category"],
                "disabled": characteristics["disabled"],
                "required_dependency": required,
                "blocking": required,
                "observed_state": state.get("state") if state else None,
                "relevance": relevance,
                "severity": severity,
                "affected_capabilities": _capabilities(characteristics),
                "reasons": relevance_reasons + severity_reasons,
            }
        )

    for entity_id, state in state_by_id.items():
        if state.get("state") == "unavailable" and entity_id in registry_by_id:
            add_issue(entity_id, "unavailable")
    for entity_id in architecture.get("exceptions", {}).get("entities_without_state", []):
        if isinstance(entity_id, str):
            add_issue(entity_id, "missing_current_state")
    for entity_id in analysis.get("state_only_entities", []):
        if isinstance(entity_id, str):
            add_issue(entity_id, "state_only")

    failed_datasets = sorted(
        name for name, status in websocket_statuses.items()
        if not status.get("success", False)
    )
    for dataset in failed_datasets:
        issues.append(
            {
                "issue_id": f"dataset_unavailable:{dataset}",
                "issue_type": "dataset_unavailable",
                "dataset": dataset,
                "required_dependency": True,
                "blocking": True,
                "relevance": "very_high",
                "severity": "critical",
                "affected_capabilities": ["discovery_validation"],
                "reasons": ["required_structural_dataset_unavailable"],
            }
        )

    severity_counts = Counter(issue["severity"] for issue in issues)
    relevance_counts = Counter(issue["relevance"] for issue in issues)
    blocking_issues = [issue for issue in issues if issue.get("blocking")]
    capability_issues: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        for capability in issue.get("affected_capabilities", []):
            capability_issues[capability].append(issue)

    if blocking_issues:
        status = "NOT_READY"
    elif severity_counts["warning"]:
        status = "READY_WITH_WARNINGS"
    else:
        status = "READY"

    capability_statuses = []
    for capability, linked in sorted(capability_issues.items()):
        if any(issue.get("blocking") for issue in linked):
            capability_status = "NOT_READY"
        elif any(issue["severity"] == "warning" for issue in linked):
            capability_status = "READY_WITH_WARNINGS"
        else:
            capability_status = "READY"
        capability_statuses.append(
            {
                "capability": capability,
                "status": capability_status,
                "issue_count": len(linked),
                "blocking_issue_count": sum(1 for issue in linked if issue.get("blocking")),
                "issue_ids": sorted(issue["issue_id"] for issue in linked),
            }
        )

    return {
        "metadata": {
            "schema": "picot_hems.discovery.readiness",
            "schema_version": "0.2.0",
            "method": "deterministic_rules_with_explicit_dependencies",
            "name_matching_used": False,
        },
        "status": status,
        "planning_allowed": not blocking_issues,
        "summary": {
            "issue_count": len(issues),
            "blocking_issue_count": len(blocking_issues),
            "required_entity_count": len(required_entity_ids),
            "severity_counts": dict(sorted(severity_counts.items())),
            "relevance_counts": dict(sorted(relevance_counts.items())),
            "failed_structural_dataset_count": len(failed_datasets),
            "capability_count": len(capability_statuses),
        },
        "capabilities": capability_statuses,
        "issues": sorted(
            issues,
            key=lambda item: (
                not item.get("blocking", False),
                {"critical": 0, "warning": 1, "informational": 2}.get(item["severity"], 3),
                str(item["issue_id"]),
            ),
        ),
        "rules": {
            "blocking": "Only failed required structural datasets or explicitly declared required entities block planning.",
            "critical": "An explicitly required dependency is unavailable or missing.",
            "warning": "Relevant observed data is unavailable but has not been declared required.",
            "informational": "Disabled, low-relevance, unknown-relevance or state-only observation.",
        },
    }
