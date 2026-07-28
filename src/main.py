"""Command-line entry point for PicoT Home Assistant discovery."""

from __future__ import annotations

from pathlib import Path

from api import HomeAssistantApiError, HomeAssistantClient
from discovery import run_discovery
from export import export_discovery_snapshot


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"


def main() -> None:
    """Run Discovery Step 2.1 and export a traceable REST snapshot."""
    try:
        client = HomeAssistantClient.from_environment()
        result = run_discovery(client)
        files = export_discovery_snapshot(result, OUTPUT_DIRECTORY)
    except (RuntimeError, HomeAssistantApiError) as exc:
        raise SystemExit(f"Discovery failed: {exc}") from exc

    summary = result["summary"]
    print("PicoT Discovery Step 2.1 completed.")
    print(f"Home Assistant version: {summary['home_assistant_version']}")
    print(f"States/entities: {summary['state_count']}")
    print(f"Entity domains: {summary['entity_domain_count']}")
    print(f"Service domains: {summary['service_domain_count']}")
    print(f"Services: {summary['service_count']}")
    print(f"JSON output: {files['snapshot'].parent}")


if __name__ == "__main__":
    main()
