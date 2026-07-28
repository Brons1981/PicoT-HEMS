"""Home Assistant REST API client for PicoT Discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv


class HomeAssistantApiError(RuntimeError):
    """Raised when Home Assistant cannot provide a valid API response."""


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
        """Perform an authenticated GET request and return decoded JSON."""
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise HomeAssistantApiError(
                f"Home Assistant did not respond within {self.timeout_seconds} seconds."
            ) from exc
        except requests.ConnectionError as exc:
            raise HomeAssistantApiError(
                f"Cannot connect to Home Assistant at {self.base_url}."
            ) from exc
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            if status_code == 401:
                message = "Home Assistant rejected the token (HTTP 401)."
            else:
                message = f"Home Assistant returned HTTP {status_code} for {path}."
            raise HomeAssistantApiError(message) from exc
        except requests.RequestException as exc:
            raise HomeAssistantApiError(f"Home Assistant request failed for {path}.") from exc

        try:
            return response.json()
        except requests.JSONDecodeError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant returned invalid JSON for {path}."
            ) from exc

    def check_api(self) -> dict[str, Any]:
        """Verify authentication and API availability."""
        data = self._get("/api/")
        if not isinstance(data, dict):
            raise HomeAssistantApiError("Unexpected response from Home Assistant /api/ endpoint.")
        return data

    def get_config(self) -> dict[str, Any]:
        """Return Home Assistant instance configuration metadata."""
        data = self._get("/api/config")
        if not isinstance(data, dict):
            raise HomeAssistantApiError("Unexpected response from /api/config.")
        return data

    def get_states(self) -> list[dict[str, Any]]:
        """Return all current Home Assistant entity states."""
        data = self._get("/api/states")
        if not isinstance(data, list):
            raise HomeAssistantApiError("Unexpected response from /api/states.")
        return data

    def get_services(self) -> list[dict[str, Any]]:
        """Return all registered Home Assistant service domains and services."""
        data = self._get("/api/services")
        if not isinstance(data, list):
            raise HomeAssistantApiError("Unexpected response from /api/services.")
        return data
