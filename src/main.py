"""Command-line entry point for PicoT Home Assistant discovery."""

from __future__ import annotations

from api import HomeAssistantClient
from discovery import run_discovery


def main() -> None:
    """Run a first connectivity and discovery check."""
    client = HomeAssistantClient.from_environment()
    result = run_discovery(client)
    print(f"Connected to Home Assistant. Retrieved {result['state_count']} states.")


if __name__ == "__main__":
    main()
