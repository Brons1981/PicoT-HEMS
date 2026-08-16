"""Read-only Home Assistant solar history for V2ADR-049."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, tzinfo
from hashlib import sha256
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SOLAR_HISTORY_SOURCE_ENTITY_ID = "sun.sun"
SOLAR_HISTORY_METHOD_VERSION = (
    "home-assistant-sun-history-attributes:v1"
)


@dataclass(frozen=True, slots=True)
class SolarContextObservation:
    evidence_id: str
    sampled_at: datetime
    solar_azimuth_degrees: float
    solar_elevation_degrees: float
    sunset_at: datetime


@dataclass(frozen=True, slots=True)
class SolarHistoryReadResult:
    source_entity_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    error: str | None
    observations: tuple[SolarContextObservation, ...]
    method_version: str


class HomeAssistantSolarHistoryReader:
    """Read one bounded sun.sun history window with attributes."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        local_timezone: tzinfo,
    ) -> SolarHistoryReadResult:
        for name, value in (
            ("starts_at", starts_at),
            ("ends_at", ends_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if starts_at >= ends_at:
            raise ValueError("starts_at must be before ends_at")

        query = urlencode(
            {
                "filter_entity_id": SOLAR_HISTORY_SOURCE_ENTITY_ID,
                "end_time": ends_at.isoformat(),
            }
        )
        request = Request(
            (
                "http://supervisor/core/api/history/period/"
                f"{quote(starts_at.isoformat(), safe='')}?{query}"
            ),
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
            return _result(
                starts_at=starts_at,
                ends_at=ends_at,
                status="unavailable",
                error=type(exc).__name__,
            )

        observations: list[SolarContextObservation] = []
        if isinstance(payload, list):
            for group in payload:
                if not isinstance(group, list):
                    continue
                for item in group:
                    observation = _decode_observation(
                        item,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        local_timezone=local_timezone,
                    )
                    if observation is not None:
                        observations.append(observation)

        ordered = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.sampled_at,
                    item.evidence_id,
                ),
            )
        )
        if not ordered:
            return _result(
                starts_at=starts_at,
                ends_at=ends_at,
                status="empty",
                error="no_valid_solar_observations",
            )
        return _result(
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=ordered,
        )


def _decode_observation(
    item: object,
    *,
    starts_at: datetime,
    ends_at: datetime,
    local_timezone: tzinfo,
) -> SolarContextObservation | None:
    if not isinstance(item, dict):
        return None
    if item.get("entity_id") != SOLAR_HISTORY_SOURCE_ENTITY_ID:
        return None

    raw_sampled_at = item.get("last_updated")
    attributes = item.get("attributes")
    if not isinstance(raw_sampled_at, str) or not isinstance(
        attributes,
        dict,
    ):
        return None

    sampled_at = _parse_aware_datetime(raw_sampled_at)
    if (
        sampled_at is None
        or not starts_at <= sampled_at <= ends_at
    ):
        return None

    azimuth = _finite_number(attributes.get("azimuth"))
    elevation = _finite_number(attributes.get("elevation"))
    raw_sunset = attributes.get("next_setting")
    if (
        azimuth is None
        or elevation is None
        or not isinstance(raw_sunset, str)
    ):
        return None
    if not 0.0 <= azimuth <= 360.0:
        return None
    if not -90.0 <= elevation <= 90.0:
        return None

    sunset = _parse_aware_datetime(raw_sunset)
    if sunset is None:
        return None
    local_sunset = sunset.astimezone(local_timezone)
    evidence_id = _evidence_id(
        sampled_at=sampled_at,
        azimuth=azimuth,
        elevation=elevation,
        sunset_at=local_sunset,
    )
    return SolarContextObservation(
        evidence_id=evidence_id,
        sampled_at=sampled_at,
        solar_azimuth_degrees=azimuth,
        solar_elevation_degrees=elevation,
        sunset_at=local_sunset,
    )


def _evidence_id(
    *,
    sampled_at: datetime,
    azimuth: float,
    elevation: float,
    sunset_at: datetime,
) -> str:
    seed = "|".join(
        (
            SOLAR_HISTORY_SOURCE_ENTITY_ID,
            sampled_at.isoformat(),
            str(azimuth),
            str(elevation),
            sunset_at.isoformat(),
            SOLAR_HISTORY_METHOD_VERSION,
        )
    )
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"evidence-solar-history-{digest}"


def _parse_aware_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _result(
    *,
    starts_at: datetime,
    ends_at: datetime,
    status: str,
    error: str | None,
    observations: tuple[SolarContextObservation, ...] = (),
) -> SolarHistoryReadResult:
    return SolarHistoryReadResult(
        source_entity_id=SOLAR_HISTORY_SOURCE_ENTITY_ID,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        error=error,
        observations=observations,
        method_version=SOLAR_HISTORY_METHOD_VERSION,
    )
