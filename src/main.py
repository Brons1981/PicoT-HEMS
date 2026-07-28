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
    """Run Discovery Step 2.4 and export structural analysis."""
    try:
        client = HomeAssistantClient.from_environment()
        result = run_discovery(client)
        files = export_discovery_snapshot(result, OUTPUT_DIRECTORY)
    except (RuntimeError, HomeAssistantApiError, HomeAssistantWebSocketError) as exc:
        raise SystemExit(f"Discovery failed: {exc}") from exc

    summary = result["summary"]
    architecture = summary["architecture"]
    analysis = summary["analysis"]

    print("PicoT Discovery Step 2.4 completed.")
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
    print(f"Unlinked categories: {analysis['unlinked_entity_categories']}")
    print(f"Integration structural statuses: {analysis['integration_status_counts']}")
    print(f"Device structural statuses: {analysis['device_status_counts']}")

    failed = [
        name
        for name, status in summary["websocket_statuses"].items()
        if not status["success"]
    ]
    if failed:
        print(f"Unavailable structural datasets: {', '.join(failed)}")
        print("Details: output\\websocket_statuses.json")

    print(f"Architecture analysis: {files['analysis']}")
    print(f"Integration health: {files['integration_health']}")
    print(f"Device health: {files['device_health']}")
    print(f"State-only entities: {files['state_only_entities']}")
    print(f"JSON output: {files['snapshot'].parent}")


if __name__ == "__main__":
    main()
