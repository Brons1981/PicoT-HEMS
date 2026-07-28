"""Home Assistant WebSocket API client for structural PicoT Discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import websocket


class HomeAssistantWebSocketError(RuntimeError):
    """Raised when Home Assistant WebSocket communication fails."""


@dataclass
class HomeAssistantWebSocketClient:
    """Small synchronous client for Home Assistant registry commands."""

    base_url: str
    token: str
    timeout_seconds: int = 30

    def _websocket_url(self) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme == "http":
            scheme = "ws"
        elif parsed.scheme == "https":
            scheme = "wss"
        else:
            raise HomeAssistantWebSocketError(
                f"Unsupported Home Assistant URL scheme: {parsed.scheme!r}."
            )
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

    def collect_structure(self) -> dict[str, Any]:
        """Authenticate once and collect Home Assistant structural registries."""
        commands = {
            "config_entries": "config_entries/get",
            "devices": "config/device_registry/list",
            "entities": "config/entity_registry/list",
            "areas": "config/area_registry/list",
            "floors": "config/floor_registry/list",
            "labels": "config/label_registry/list",
        }

        try:
            connection = websocket.create_connection(
                self._websocket_url(), timeout=self.timeout_seconds
            )
        except Exception as exc:  # websocket-client exposes several exception types
            raise HomeAssistantWebSocketError(
                f"Could not connect to Home Assistant WebSocket API: {exc}"
            ) from exc

        try:
            self._authenticate(connection)
            datasets: dict[str, Any] = {}
            statuses: dict[str, dict[str, Any]] = {}

            for request_id, (name, command_type) in enumerate(commands.items(), start=1):
                response = self._request(connection, request_id, command_type)
                if response.get("success") is True:
                    datasets[name] = response.get("result", [])
                    statuses[name] = {"success": True, "command": command_type}
                else:
                    error = response.get("error", {})
                    datasets[name] = []
                    statuses[name] = {
                        "success": False,
                        "command": command_type,
                        "error": error,
                    }

            return {"datasets": datasets, "statuses": statuses}
        finally:
            connection.close()

    def _authenticate(self, connection: websocket.WebSocket) -> None:
        initial = self._receive_json(connection)
        if initial.get("type") != "auth_required":
            raise HomeAssistantWebSocketError(
                f"Unexpected WebSocket authentication message: {initial!r}"
            )

        connection.send(json.dumps({"type": "auth", "access_token": self.token}))
        response = self._receive_json(connection)
        if response.get("type") != "auth_ok":
            message = response.get("message", "authentication rejected")
            raise HomeAssistantWebSocketError(
                f"Home Assistant WebSocket authentication failed: {message}"
            )

    def _request(
        self, connection: websocket.WebSocket, request_id: int, command_type: str
    ) -> dict[str, Any]:
        connection.send(json.dumps({"id": request_id, "type": command_type}))

        while True:
            response = self._receive_json(connection)
            if response.get("id") == request_id:
                return response

    @staticmethod
    def _receive_json(connection: websocket.WebSocket) -> dict[str, Any]:
        raw = connection.recv()
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise HomeAssistantWebSocketError(
                "Home Assistant returned invalid WebSocket JSON."
            ) from exc
        if not isinstance(data, dict):
            raise HomeAssistantWebSocketError(
                "Home Assistant returned an unexpected WebSocket payload."
            )
        return data
