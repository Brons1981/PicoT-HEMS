"""Recorded sun states for financial night evidence; no solar-attribute dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

METHOD_VERSION = "home-assistant-sun-state-history:v1"
SOURCE_ENTITY_ID = "sun.sun"
MAX_OBSERVATIONS = 4096


@dataclass(frozen=True)
class SunStateObservation:
    evidence_id: str
    sampled_at: datetime
    state: str


@dataclass(frozen=True)
class SunStateHistoryReadResult:
    source_entity_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    error: str | None
    observations: tuple[SunStateObservation, ...] = ()
    method_version: str = METHOD_VERSION


class HomeAssistantSunStateHistoryReader:
    """Read a bounded Recorder window, including its unchanged starting state."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(self, *, starts_at: datetime, ends_at: datetime) -> SunStateHistoryReadResult:
        if any(value.tzinfo is None or value.utcoffset() is None
               for value in (starts_at, ends_at)) or starts_at >= ends_at:
            raise ValueError("sun history requires an ordered timezone-aware window")
        starts_at, ends_at = starts_at.astimezone(UTC), ends_at.astimezone(UTC)

        def result(status: str, error: str | None,
                   points: tuple[SunStateObservation, ...] = ()) -> SunStateHistoryReadResult:
            return SunStateHistoryReadResult(SOURCE_ENTITY_ID, starts_at, ends_at,
                                             status, error, points)

        query = urlencode({"filter_entity_id": SOURCE_ENTITY_ID,
                           "end_time": ends_at.isoformat(), "no_attributes": "true"})
        request = Request(
            "http://supervisor/core/api/history/period/"
            f"{quote(starts_at.isoformat(), safe='')}?{query}",
            headers={"Authorization": f"Bearer {self._token}"}, method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload: object = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return result("unavailable", type(exc).__name__)
        if not isinstance(payload, list):
            return result("unavailable", "invalid_sun_state_history")
        points: dict[datetime, SunStateObservation] = {}
        for group in payload:
            if not isinstance(group, list):
                return result("unavailable", "invalid_sun_state_history")
            for item in group:
                if not isinstance(item, dict):
                    return result("unavailable", "invalid_sun_state_history")
                if not isinstance(item.get("entity_id"), str):
                    return result("unavailable", "invalid_sun_state_history")
                if item.get("entity_id") != SOURCE_ENTITY_ID:
                    continue
                raw_time = item.get("last_updated") or item.get("last_changed")
                try:
                    at = datetime.fromisoformat(raw_time) if isinstance(raw_time, str) else None
                except ValueError:
                    at = None
                if at is None or at.tzinfo is None or at.utcoffset() is None:
                    return result("unavailable", "invalid_sun_state_timestamp")
                at = at.astimezone(UTC)
                if at > ends_at:
                    continue
                state = item.get("state")
                if state not in ("above_horizon", "below_horizon"):
                    state = "unavailable"
                if at in points and points[at].state != state:
                    return result("unavailable", "ambiguous_sun_state_history")
                seed = f"{METHOD_VERSION}|{at.isoformat()}|{state}"
                digest = sha256(seed.encode()).hexdigest()[:16]
                points[at] = SunStateObservation(f"evidence-sun-state-{digest}", at, state)
                if len(points) > MAX_OBSERVATIONS:
                    return result("unavailable", "sun_state_history_resource_limit")
        ordered = sorted(points.values(), key=lambda p: p.sampled_at)
        # Recorder may return an anchor whose actual change precedes the query.
        anchors = [p for p in ordered if p.sampled_at <= starts_at]
        bounded = (*anchors[-1:], *(p for p in ordered if p.sampled_at > starts_at))
        if not bounded:
            return result("empty", "no_sun_state_observations")
        return result("available", None, bounded)
