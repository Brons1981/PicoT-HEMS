"""Canonical read-only power history for PicoT dashboard consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class PowerSeriesSpec:
    """Declare one canonical series derived from one HA power entity."""

    series_id: str
    role: str
    entity_id: str
    transform: str = "identity"

    def __post_init__(self) -> None:
        if not self.series_id.strip() or not self.role.strip():
            raise ValueError("series_id and role must be explicit")
        if not self.entity_id.strip():
            raise ValueError("entity_id must be explicit")
        if self.transform not in {
            "identity",
            "positive",
            "negative_magnitude",
        }:
            raise ValueError("unsupported power history transform")


@dataclass(frozen=True, slots=True)
class PowerHistoryPoint:
    sampled_at: datetime
    power_w: float
    evidence_id: str


@dataclass(frozen=True, slots=True)
class PowerHistorySeries:
    series_id: str
    role: str
    source_entity_id: str
    transform: str
    points: tuple[PowerHistoryPoint, ...]
    history_semantics: str = "state_hold"

    def __post_init__(self) -> None:
        if self.history_semantics not in {"state_hold", "sampled_linear"}:
            raise ValueError("unsupported power history semantics")


@dataclass(frozen=True, slots=True)
class PowerHistorySnapshot:
    starts_at: datetime
    ends_at: datetime
    status: str
    error: str | None
    series: tuple[PowerHistorySeries, ...]
    method_version: str = "home-assistant-power-history:v1"


class HomeAssistantPowerHistoryReader:
    """Read multiple HA power histories in one bounded request."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(
        self,
        *,
        specs: tuple[PowerSeriesSpec, ...],
        starts_at: datetime,
        ends_at: datetime,
    ) -> PowerHistorySnapshot:
        if not specs:
            raise ValueError("at least one power series spec is required")
        for name, value in (("starts_at", starts_at), ("ends_at", ends_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if starts_at >= ends_at:
            raise ValueError("starts_at must be before ends_at")

        entity_ids = tuple(dict.fromkeys(spec.entity_id for spec in specs))
        query = urlencode({
            "filter_entity_id": ",".join(entity_ids),
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
                payload: object = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return PowerHistorySnapshot(
                starts_at=starts_at,
                ends_at=ends_at,
                status="unavailable",
                error=type(exc).__name__,
                series=(),
            )

        raw_by_entity: dict[str, list[tuple[datetime, float, str]]] = {
            entity_id: [] for entity_id in entity_ids
        }
        if isinstance(payload, list):
            for group in payload:
                if not isinstance(group, list):
                    continue
                for item in group:
                    decoded = _decode_item(
                        item,
                        allowed_entity_ids=frozenset(entity_ids),
                        starts_at=starts_at,
                        ends_at=ends_at,
                    )
                    if decoded is not None:
                        entity_id, sampled_at, power_w, evidence_id = decoded
                        raw_by_entity[entity_id].append(
                            (sampled_at, power_w, evidence_id)
                        )

        series = tuple(
            PowerHistorySeries(
                series_id=spec.series_id,
                role=spec.role,
                source_entity_id=spec.entity_id,
                transform=spec.transform,
                points=tuple(
                    PowerHistoryPoint(
                        sampled_at=sampled_at,
                        power_w=_transform_power(power_w, spec.transform),
                        evidence_id=evidence_id,
                    )
                    for sampled_at, power_w, evidence_id in sorted(
                        raw_by_entity[spec.entity_id],
                        key=lambda item: (item[0], item[2]),
                    )
                ),
            )
            for spec in specs
        )
        return PowerHistorySnapshot(
            starts_at=starts_at,
            ends_at=ends_at,
            status=(
                "available"
                if any(item.points for item in series)
                else "empty"
            ),
            error=None,
            series=series,
        )


HISTORY_BOOTSTRAP_CHUNK = timedelta(hours=2)


class PowerHistoryCache:
    """Retain today's series and request only the unseen time tail."""

    def __init__(self) -> None:
        self._snapshot: PowerHistorySnapshot | None = None

    def update(
        self,
        reader: HomeAssistantPowerHistoryReader,
        *,
        specs: tuple[PowerSeriesSpec, ...],
        starts_at: datetime,
        ends_at: datetime,
    ) -> PowerHistorySnapshot:
        """Fill the bounded requested window now, retaining chunk retry safety."""

        result = self._update_chunk(
            reader,
            specs=specs,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        while result.status != "unavailable" and result.ends_at < ends_at:
            previous_end = result.ends_at
            result = self._update_chunk(
                reader,
                specs=specs,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if result.ends_at <= previous_end or result.error is not None:
                break
        return result

    def _update_chunk(
        self,
        reader: HomeAssistantPowerHistoryReader,
        *,
        specs: tuple[PowerSeriesSpec, ...],
        starts_at: datetime,
        ends_at: datetime,
    ) -> PowerHistorySnapshot:
        previous = self._snapshot
        same_window = previous is not None and previous.starts_at == starts_at
        read_starts_at = (
            max(starts_at, previous.ends_at)
            if same_window and previous is not None
            else starts_at
        )
        if read_starts_at >= ends_at and previous is not None:
            return previous
        read_ends_at = min(read_starts_at + HISTORY_BOOTSTRAP_CHUNK, ends_at)
        latest = reader.read(
            specs=specs,
            starts_at=read_starts_at,
            ends_at=read_ends_at,
        )
        if previous is None or not same_window:
            if latest.status == "unavailable":
                return latest
            self._snapshot = latest
            return latest
        if latest.status == "unavailable":
            return replace_snapshot_error(previous, latest.error)

        previous_by_id = {item.series_id: item for item in previous.series}
        merged_series: list[PowerHistorySeries] = []
        for latest_series in latest.series:
            prior = previous_by_id.get(latest_series.series_id)
            combined = (
                (*prior.points, *latest_series.points)
                if prior is not None
                else latest_series.points
            )
            unique = {
                point.evidence_id: point
                for point in combined
            }
            merged_series.append(
                PowerHistorySeries(
                    series_id=latest_series.series_id,
                    role=latest_series.role,
                    source_entity_id=latest_series.source_entity_id,
                    transform=latest_series.transform,
                    history_semantics=latest_series.history_semantics,
                    points=tuple(sorted(
                        unique.values(),
                        key=lambda point: (
                            point.sampled_at,
                            point.evidence_id,
                        ),
                    )),
                )
            )
        merged = PowerHistorySnapshot(
            starts_at=starts_at,
            ends_at=read_ends_at,
            status=(
                "available"
                if any(item.points for item in merged_series)
                else "empty"
            ),
            error=None,
            series=tuple(merged_series),
        )
        self._snapshot = merged
        return merged


def replace_snapshot_error(
    snapshot: PowerHistorySnapshot,
    error: str | None,
) -> PowerHistorySnapshot:
    """Keep proven points while exposing an incremental read failure."""
    return PowerHistorySnapshot(
        starts_at=snapshot.starts_at,
        ends_at=snapshot.ends_at,
        status=snapshot.status,
        error=error,
        series=snapshot.series,
        method_version=snapshot.method_version,
    )


def _transform_power(value: float, transform: str) -> float:
    if transform == "positive":
        return max(0.0, value)
    if transform == "negative_magnitude":
        return max(0.0, -value)
    return value


def _decode_item(
    item: object,
    *,
    allowed_entity_ids: frozenset[str],
    starts_at: datetime,
    ends_at: datetime,
) -> tuple[str, datetime, float, str] | None:
    if not isinstance(item, dict):
        return None
    entity_id = item.get("entity_id")
    raw_state = item.get("state")
    raw_timestamp = item.get("last_updated")
    if (
        not isinstance(entity_id, str)
        or entity_id not in allowed_entity_ids
        or not isinstance(raw_state, str)
        or not isinstance(raw_timestamp, str)
        or raw_state.strip().lower() in {"unknown", "unavailable"}
    ):
        return None
    try:
        sampled_at = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        power_w = float(raw_state)
    except ValueError:
        return None
    if (
        sampled_at.tzinfo is None
        or sampled_at.utcoffset() is None
        or not starts_at <= sampled_at <= ends_at
        or not isfinite(power_w)
    ):
        return None
    seed = f"{entity_id}|{sampled_at.isoformat()}|{raw_state}"
    evidence_id = (
        "evidence-power-history-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )
    return entity_id, sampled_at, power_w, evidence_id
