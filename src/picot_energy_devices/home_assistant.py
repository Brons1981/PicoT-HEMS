"""Narrow read-only Home Assistant client plus catalog publication."""

from __future__ import annotations

import json
from math import isfinite
from urllib.parse import quote
from urllib.request import Request, urlopen


class HomeAssistantClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def _request(self, request: Request) -> dict[str, object]:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, dict):
            raise ValueError("Home Assistant response must be an object")
        return payload

    def state(self, entity_id: str) -> dict[str, object]:
        return self._request(
            Request(
                "http://supervisor/core/api/states/" + quote(entity_id, safe="."),
                headers={"Authorization": f"Bearer {self._token}"},
            )
        )

    @staticmethod
    def measurement(payload: dict[str, object], *, quantity: str) -> float:
        raw = payload.get("state")
        if not isinstance(raw, str) or raw.casefold() in {"unknown", "unavailable"}:
            raise ValueError(f"{quantity} state is unavailable")
        value = float(raw)
        if not isfinite(value):
            raise ValueError(f"{quantity} state must be finite")
        attributes = payload.get("attributes")
        unit = attributes.get("unit_of_measurement") if isinstance(attributes, dict) else None
        normalized = str(unit or "").strip().casefold()
        if quantity == "power":
            if normalized == "kw":
                return value * 1000.0
            if normalized not in {"", "w"}:
                raise ValueError(f"unsupported power unit: {unit}")
        elif quantity == "energy":
            if normalized == "kwh":
                return value * 1000.0
            if normalized not in {"", "wh"}:
                raise ValueError(f"unsupported energy unit: {unit}")
        return value

    def publish_catalog(self, entity_id: str, catalog: dict[str, object]) -> None:
        body = json.dumps(
            {
                "state": "ready",
                "attributes": {
                    **catalog,
                    "friendly_name": "PicoT Energy Devices catalogus",
                    "icon": "mdi:power-plug-outline",
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self._request(
            Request(
                "http://supervisor/core/api/states/" + quote(entity_id, safe="."),
                data=body,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
        )
