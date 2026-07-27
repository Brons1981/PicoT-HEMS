"""Discovery orchestration for PicoT HEMS."""

from __future__ import annotations

from typing import Any

from api import HomeAssistantClient


def run_discovery(client: HomeAssistantClient) -> dict[str, Any]:
    """Validate the API connection and collect the first discovery dataset."""
    api_status = client.check_api()
    states = client.get_states()

    return {
        "api_status": api_status,
        "state_count": len(states),
        "states": states,
    }
