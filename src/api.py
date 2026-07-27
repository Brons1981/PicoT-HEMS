"""Minimal Home Assistant REST API client for PicoT Discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv


@dataclass(frozen=True)
class HomeAssistantClient:
    """Authenticated client for the Home Assistant REST API."""

    base_url: str
    token: str
    timeout_seconds: int = 30

    @classmethod
    def from_environment(cls) -> "HomeAssistantClient":
        """Load Home Assistant connection settings from a local .env file."""
        load_dotenv()
        base_url = os.getenv("HA_URL", "").strip().rstrip("/")
        token = os.getenv("HA_TOKEN", "").strip()

        if not base_url:
            raise RuntimeError("HA_URL is missing. Copy .env.example to .env and set HA_URL.")
        if not token or token == "replace_with_your_long_lived_access_token":
            raise RuntimeError("HA_TOKEN is missing. Add your Long-Lived Access Token to .env.")

        return cls(base_url=base_url, token=token)

    def _get(self, path: str) -> Any:
        response = requests.get(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def check_api(self) -> dict[str, Any]:
        """Verify authentication and API availability."""
        return self._get("/api/")

    def get_states(self) -> list[dict[str, Any]]:
        """Return all current Home Assistant entity states."""
        data = self._get("/api/states")
        if not isinstance(data, list):
            raise RuntimeError("Unexpected response from Home Assistant /api/states endpoint.")
        return data
