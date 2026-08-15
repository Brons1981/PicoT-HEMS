"""Read-only Home Assistant sunset evidence for V2ADR-049."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SUNSET_SOURCE_ENTITY_ID = "sun.sun"
SUNSET_SOURCE_METHOD_VERSION = "home-assistant-sun-next-setting:v1"


@dataclass(frozen=True, slots=True)
class SunsetReadResult:
    source_entity_id: str
    status: str
    error: str | None
    source_updated_at: datetime | None
    sunsets_by_local_date: tuple[tuple[date, datetime], ...]
    method_version: str

    def __post_init__(self) -> None:
        if self.status not in ("available", "unavailable"):
            raise ValueError("status must be available or unavailable")
        if self.status == "available" and not self.sunsets_by_local_date:
            raise ValueError("available result requires sunset evidence")
        if self.status == "unavailable" and self.error is None:
            raise ValueError("unavailable result requires an error")
        if not self.method_version.strip():
            raise ValueError("method_version must be explicit")


class HomeAssistantSunsetReader:
    """Read the one next setting exposed by Home Assistant."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(self, *, local_timezone: tzinfo) -> SunsetReadResult:
        request = Request(
            "http://supervisor/core/api/states/sun.sun",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload: object = json.loads(
                    response.read().decode("utf-8")
                )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            return _unavailable(type(exc).__name__)

        if not isinstance(payload, dict):
            return _unavailable("source_payload_invalid")
        if payload.get("entity_id") != SUNSET_SOURCE_ENTITY_ID:
            return _unavailable("source_entity_mismatch")

        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            return _unavailable("attributes_missing")
        raw_next_setting = attributes.get("next_setting")
        if not isinstance(raw_next_setting, str) or not raw_next_setting.strip():
            return _unavailable("next_setting_missing")

        next_setting = _parse_aware_datetime(raw_next_setting)
        if next_setting is None:
            return _unavailable("next_setting_invalid")
        local_setting = next_setting.astimezone(local_timezone)

        raw_updated_at = payload.get("last_updated")
        source_updated_at = (
            _parse_aware_datetime(raw_updated_at)
            if isinstance(raw_updated_at, str)
            else None
        )
        if source_updated_at is None:
            return _unavailable("source_updated_at_invalid")

        return SunsetReadResult(
            source_entity_id=SUNSET_SOURCE_ENTITY_ID,
            status="available",
            error=None,
            source_updated_at=source_updated_at,
            sunsets_by_local_date=(
                (local_setting.date(), local_setting),
            ),
            method_version=SUNSET_SOURCE_METHOD_VERSION,
        )


def _parse_aware_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _unavailable(error: str) -> SunsetReadResult:
    return SunsetReadResult(
        source_entity_id=SUNSET_SOURCE_ENTITY_ID,
        status="unavailable",
        error=error,
        source_updated_at=None,
        sunsets_by_local_date=(),
        method_version=SUNSET_SOURCE_METHOD_VERSION,
    )
