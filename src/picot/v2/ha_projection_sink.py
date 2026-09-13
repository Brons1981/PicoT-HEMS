"""Home Assistant transport for PicoT v2 diagnostic cards only."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from picot.v2.projection import Card

# Leave room below Recorder's 16 KiB limit for HA serialization/metadata.
_ATTRIBUTE_BUDGET_BYTES = 12_000


def _serialized_size(value: object) -> int:
    # Default spacing and ASCII escaping conservatively bound the UTF-8 payload.
    return len(json.dumps(value).encode("utf-8"))


def _ha_attributes(attributes: dict[str, object]) -> dict[str, object]:
    """Bound only the HA transport; canonical and dashboard cards stay complete."""
    if _serialized_size(attributes) <= _ATTRIBUTE_BUDGET_BYTES:
        return attributes

    compact = dict(attributes)
    omitted: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "compacted": True,
        "full_details": "PicoT dashboard and diagnostics",
        "omitted_field_count": 0,
        "omitted_fields": omitted,
    }
    # Largest fields go first, preserving useful scalar status and timestamps.
    fields = sorted(
        attributes,
        key=lambda name: _serialized_size({name: attributes[name]}),
        reverse=True,
    )
    for index, name in enumerate(fields, start=1):
        value = compact.pop(name, None)
        if len(omitted) < 16:
            detail: dict[str, object] = {"field": name[:32]}
            if isinstance(value, (dict, list, tuple)):
                detail["item_count"] = len(value)
            elif isinstance(value, str):
                detail["character_count"] = len(value)
            omitted.append(detail)
        summary["omitted_field_count"] = index
        compact["_picot_ha_summary"] = summary
        if _serialized_size(compact) <= _ATTRIBUTE_BUDGET_BYTES:
            break
    return compact


class HomeAssistantProjectionSink:
    """Publish already-built diagnostic cards to Home Assistant state entities."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def publish(self, card: Card) -> None:
        body = json.dumps(
            {"state": card.state, "attributes": _ha_attributes(card.attributes)},
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
