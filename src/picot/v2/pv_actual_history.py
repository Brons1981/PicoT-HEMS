"""Read-only Home Assistant history ingestion for actual PV power."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from picot.v2.pv_actual_intervals import PVPowerObservation


@dataclass(frozen=True, slots=True)
class PVHistoryReadResult:
    entity_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    error: str | None
    observations: tuple[PVPowerObservation, ...]


def _evidence_id(
    entity_id: str,
    sampled_at: datetime,
    power_w: float,
) -> str:
    seed = f"{entity_id}|{sampled_at.isoformat()}|{power_w}"
    digest = sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"evidence-pv-history-{digest}"


class HomeAssistantPVHistoryReader:
    """Read one bounded PV-power history window without side effects."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(
        self,
        *,
        entity_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> PVHistoryReadResult:
        if not entity_id.strip():
            raise ValueError("entity_id must be explicit")
        for name, value in (
            ("starts_at", starts_at),
            ("ends_at", ends_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if starts_at >= ends_at:
            raise ValueError("starts_at must be before ends_at")

        query = urlencode({
            "filter_entity_id": entity_id,
            "end_time": ends_at.isoformat(),
            "no_attributes": "1",
        })
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
            return PVHistoryReadResult(
                entity_id=entity_id,
                starts_at=starts_at,
                ends_at=ends_at,
                status="unavailable",
                error=type(exc).__name__,
                observations=(),
            )

        observations: list[PVPowerObservation] = []
        if isinstance(payload, list):
            for group in payload:
                if not isinstance(group, list):
                    continue
                for item in group:
                    observation = _decode_observation(
                        item,
                        entity_id=entity_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
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
        return PVHistoryReadResult(
            entity_id=entity_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="available" if ordered else "empty",
            error=None,
            observations=ordered,
        )


def _decode_observation(
    item: object,
    *,
    entity_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> PVPowerObservation | None:
    if not isinstance(item, dict):
        return None
    if item.get("entity_id") != entity_id:
        return None

    raw_state = item.get("state")
    raw_timestamp = item.get("last_updated")
    if not isinstance(raw_state, str) or not isinstance(
        raw_timestamp,
        str,
    ):
        return None

    try:
        power_w = float(raw_state)
        sampled_at = datetime.fromisoformat(
            raw_timestamp.replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if (
        not isfinite(power_w)
        or power_w < 0.0
        or sampled_at.tzinfo is None
        or sampled_at.utcoffset() is None
        or not starts_at <= sampled_at <= ends_at
    ):
        return None

    return PVPowerObservation(
        power_w=power_w,
        sampled_at=sampled_at,
        evidence_id=_evidence_id(
            entity_id,
            sampled_at,
            power_w,
        ),
    )
