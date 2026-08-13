"""Persistent JSONL history for PicoT runtime evidence."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_HISTORY_PATH = Path("/data/picot_history.jsonl")
FULL_RETENTION_HOURS = 72
MEDIUM_RETENTION_DAYS = 30
LONG_RETENTION_DAYS = 90
MEDIUM_BUCKET_SECONDS = 60
LONG_BUCKET_SECONDS = 900
RECENT_INDEX_HOURS = 2
FORENSIC_EVENTS = {
    "picot_price_decision",
    "picot_pv_deviation_evaluator",
    "picot_plan_review",
    "picot_diagnostics_timeline",
    "picot_scheduled_transition",
    "picot_runtime_error",
}


class HistoryStore:
    """Append runtime evidence and periodically compact expired raw detail.

    JSONL remains the durable source of truth. A bounded in-memory recent index is
    rebuilt deterministically at startup and maintained on append so short recent
    range reads do not rescan the full persisted history on every telemetry poll.
    """

    def __init__(self, path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.path = path
        self._last_prune_date: date | None = None
        self._recent: deque[tuple[datetime, dict[str, object]]] = deque()
        self._recent_index_start: datetime | None = None
        self._rebuild_recent_index()

    def append(self, event: Mapping[str, object]) -> None:
        """Persist one structured event as a JSON line and update the recent index."""

        persisted = dict(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(persisted, separators=(",", ":"), default=str))
            handle.write("\n")

        try:
            timestamp = _event_timestamp(persisted)
        except (TypeError, ValueError):
            timestamp = None
        if timestamp is not None:
            self._recent.append((timestamp, persisted))
            self._trim_recent_index(timestamp)

        now = datetime.now().astimezone()
        if self._last_prune_date != now.date():
            self.prune(now)
            self._last_prune_date = now.date()

    def iter_range(self, start: datetime, end: datetime) -> Iterator[dict[str, object]]:
        """Yield persisted events whose event timestamp falls inside [start, end].

        Recent reads are served from the in-memory index when that index fully
        covers the requested interval. Older reads fall back to the durable JSONL
        scan so retention/export semantics remain unchanged.
        """

        if end < start:
            raise ValueError("end must not be before start")
        if not self.path.exists():
            return

        if self._recent_index_start is not None and start >= self._recent_index_start:
            for timestamp, event in self._recent:
                if timestamp < start:
                    continue
                if timestamp > end:
                    continue
                yield dict(event)
            return

        yield from self._iter_persisted_range(start, end)

    def _iter_persisted_range(
        self, start: datetime, end: datetime
    ) -> Iterator[dict[str, object]]:
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    timestamp = _event_timestamp(event)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if start <= timestamp <= end:
                    yield event

    def _rebuild_recent_index(self) -> None:
        """Rebuild the bounded recent index once from durable history at startup."""

        if not self.path.exists():
            return
        newest: datetime | None = None
        parsed: list[tuple[datetime, dict[str, object]]] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    timestamp = _event_timestamp(event)
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                parsed.append((timestamp, event))
                if newest is None or timestamp > newest:
                    newest = timestamp
        if newest is None:
            return
        cutoff = newest - timedelta(hours=RECENT_INDEX_HOURS)
        self._recent = deque(
            (timestamp, event) for timestamp, event in parsed if timestamp >= cutoff
        )
        self._recent_index_start = cutoff

    def _trim_recent_index(self, newest: datetime) -> None:
        cutoff = newest - timedelta(hours=RECENT_INDEX_HOURS)
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()
        self._recent_index_start = cutoff

    def prune(self, now: datetime | None = None) -> None:
        """Keep 72h full detail, then progressively downsample through 90 days."""

        if not self.path.exists():
            return

        current = now or datetime.now().astimezone()
        full_cutoff = current - timedelta(hours=FULL_RETENTION_HOURS)
        medium_cutoff = current - timedelta(days=MEDIUM_RETENTION_DAYS)
        long_cutoff = current - timedelta(days=LONG_RETENTION_DAYS)

        kept: list[str] = []
        seen_medium: set[tuple[str, str, int]] = set()
        seen_long: set[tuple[str, str, int]] = set()

        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                timestamp = _event_timestamp(event)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

            if timestamp >= full_cutoff:
                kept.append(line)
                continue

            event_name = str(event.get("event", "unknown"))
            if event_name in FORENSIC_EVENTS and timestamp >= long_cutoff:
                kept.append(line)
                continue

            source = _event_source(event)
            epoch_seconds = int(timestamp.timestamp())

            if timestamp >= medium_cutoff:
                key = (
                    event_name,
                    source,
                    epoch_seconds // MEDIUM_BUCKET_SECONDS,
                )
                if key not in seen_medium:
                    seen_medium.add(key)
                    kept.append(line)
                continue

            if timestamp >= long_cutoff:
                key = (
                    event_name,
                    source,
                    epoch_seconds // LONG_BUCKET_SECONDS,
                )
                if key not in seen_long:
                    seen_long.add(key)
                    kept.append(line)

        content = "\n".join(kept)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")


def _event_source(event: Mapping[str, object]) -> str:
    """Return a stable source key so each layer/entity downsamples independently."""

    for key in ("source_entity", "p1_entity", "stream", "layer"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return "default"


def _event_timestamp(event: Mapping[str, object]) -> datetime:
    """Resolve the timestamp used for retention and range export."""

    value = (
        event.get("observed_at")
        or event.get("captured_at")
        or event.get("evaluated_at")
        or event.get("executed_at")
        or event.get("telemetry_updated_at")
    )
    if not isinstance(value, str):
        raise ValueError("history event has no timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed
