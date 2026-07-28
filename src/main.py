"""Command-line entry point for PicoT Home Assistant discovery."""

from __future__ import annotations

from pathlib import Path

from api import HomeAssistantApiError, HomeAssistantClient
from capability_discovery import discover_capabilities
from capability_selection import select_capabilities
from discovery import run_discovery
from export import (
    export_capability_discovery,
    export_capability_selection,
    export_discovery_snapshot,
)
from websocket_api import HomeAssistantWebSocketError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"


def main() -> None:
    """Run Discovery through Capability Selection Step 2.7."""
    try:
        client = HomeAssistantClient.from_environment()
        result = run_discovery(client)
        files = export_discovery_snapshot(result, OUTPUT_DIRECTORY)

        capability_result = discover_capabilities(
            result["structure"],
            result["states"],
        )
        capability_files = export_capability_discovery(
            capability_result,
            OUTPUT_DIRECTORY,
        )

        selection_result = select_capabilities(capability_result)
        selection_files = export_capability_selection(
            selection_result,
            OUTPUT_DIRECTORY,
        )
    except (RuntimeError, HomeAssistantApiError, HomeAssistantWebSocketError) as exc:
        raise SystemExit(f"Discovery failed: {exc}") from exc

    summary = result["summary"]
    architecture = summary["architecture"]
    analysis = summary["analysis"]
    readiness = summary["readiness"]
    capability_summary = capability_result["summary"]
    selection_summary = selection_result["summary"]

    print("PicoT Discovery Step 2.7 completed.")
    print(f"Home Assistant version: {summary['home_assistant_version']}")
    print(f"States/entities: {summary['state_count']}")
    print(f"Config entries/integrations: {summary['config_entry_count']}")
    print(f"Devices: {summary['device_count']}")
    print(f"Entity registry entries: {summary['entity_registry_count']}")
    print(f"Areas: {summary['area_count']}")
    print(f"Linked devices: {architecture['linked_device_count']}")
    print(f"Orphan devices: {architecture['orphan_device_count']}")
    print(f"State-only entities: {analysis['state_only_entity_count']}")
    print(f"Unlinked entities classified: {analysis['unlinked_entity_count']}")
    print(f"Discovery readiness: {readiness['status']}")
    print(f"Planning allowed: {readiness['planning_allowed']}")
    print(f"Readiness issues: {readiness['issue_count']}")
    print(f"Severity counts: {readiness['severity_counts']}")
    print(f"Relevance counts: {readiness['relevance_counts']}")
    print(f"Capability readiness records: {readiness['capability_count']}")
    print(f"Capability definitions: {capability_summary['capability_count']}")
    print(f"Populated capabilities: {capability_summary['populated_capability_count']}")
    print(f"Capability candidates: {capability_summary['candidate_count']}")
    print(f"Entities evaluated for capabilities: {capability_summary['entities_evaluated']}")
    print(f"Selected capabilities: {selection_summary['selected_capability_count']}")
    print(f"Unselected capabilities: {selection_summary['unselected_capability_count']}")
    print(f"Selection statuses: {selection_summary['status_counts']}")

    failed = [
        name
        for name, status in summary["websocket_statuses"].items()
        if not status["success"]
    ]
    if failed:
        print(f"Unavailable structural datasets: {', '.join(failed)}")
        print("Details: output\\websocket_statuses.json")

    print(f"Discovery readiness: {files['readiness']}")
    print(f"Readiness issues: {files['readiness_issues']}")
    print(f"Capability readiness: {files['capability_readiness']}")
    print(f"Capability candidates: {capability_files['candidates']}")
    print(f"Capability statistics: {capability_files['statistics']}")
    print(f"Capability mapping: {selection_files['mapping']}")
    print(f"Capability selection audit: {selection_files['audit']}")
    print(f"Capability selection summary: {selection_files['summary']}")
    print(f"JSON output: {files['snapshot'].parent}")


if __name__ == "__main__":
    main()
