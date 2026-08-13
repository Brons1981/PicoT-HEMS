"""Home Assistant transport for PicoT v2 diagnostic cards only."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from picot.v2.projection import Card


class HomeAssistantProjectionSink:
    """Publish already-built diagnostic cards to Home Assistant state entities."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def publish(self, card: Card) -> None:
        body = json.dumps(
            {"state": card.state, "attributes": card.attributes},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"http://supervisor/core/api/states/{card.entity_id}",
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            response.read()
