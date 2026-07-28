"""Command-line entry point for PicoT Home Assistant discovery."""

from __future__ import annotations

from pathlib import Path

from api import HomeAssistantApiError, HomeAssistantClient
from discovery import run_discovery
from export import export_discovery_snapshot
from websocket_api import HomeAssistantWebSocketError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"


def main() -> None:
    """Run Discovery Step 2.5 and export readiness analysis."""
    try:
        client = HomeAssistantClient.from_environment()
        result = run_discovery(client)
        files = export_discovery_snapshot(result, OUTPUT_DIRECTORY)
    except (RuntimeError, HomeAssistantApiError, HomeAssistantWebSocketError) as exc:
        raise SystemExit(f"Discovery failed: {exc}") from exc

    summary = result["summary"]
    architecture = summary["architecture"]
    analysis = summary["analysis"]
    readiness = summary["readiness"]

    print("PicoT Discovery Step 2.5 completed.")
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
    print(f"JSON output: {files['snapshot'].parent}")


if __name__ == "__main__":
    main()
