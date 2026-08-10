"""Persistent JSONL history for PicoT runtime evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_HISTORY_PATH = Path("/data/picot_history.jsonl")
RAW_RETENTION_DAYS = 7
LONG_RETENTION_DAYS = 90
LONG_RETENTION_EVENTS = {
    "picot_price_decision",
    "picot_pv_deviation_evaluator",
}


class HistoryStore:
    """Append runtime evidence and periodically prune expired records."""

    def __init__(self, path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.path = path
        self._last_prune_date: date | None = None

    def append(self, event: Mapping[str, object]) -> None:
        """Persist one structured event as a JSON line."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), separators=(",", ":"), default=str))
            handle.write("\n")

        now = datetime.now().astimezone()
        if self._last_prune_date != now.date():
            self.prune(now)
            self._last_prune_date = now.date()

    def prune(self, now: datetime | None = None) -> None:
        """Keep raw telemetry 7 days and decision/deviation evidence 90 days."""

        if not self.path.exists():
            return
        current = now or datetime.now().astimezone()
        raw_cutoff = current - timedelta(days=RAW_RETENTION_DAYS)
        long_cutoff = current - timedelta(days=LONG_RETENTION_DAYS)
        kept: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                timestamp = _event_timestamp(event)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            cutoff = (
                long_cutoff
                if event.get("event") in LONG_RETENTION_EVENTS
                else raw_cutoff
            )
            if timestamp >= cutoff:
                kept.append(line)
        content = "\n".join(kept)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")


def _event_timestamp(event: Mapping[str, object]) -> datetime:
    """Resolve the timestamp used for retention."""

    value = event.get("observed_at") or event.get("evaluated_at")
    if not isinstance(value, str):
        raise ValueError("history event has no timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed
