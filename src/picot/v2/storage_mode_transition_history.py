"""Durable append-only audit history for planner-owned storage-mode changes."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StorageModeTransitionEvent:
    """One dispatched transition with decision and lineage facts."""

    event_id: str
    occurred_at: datetime
    previous_vendor_mode: str
    requested_vendor_mode: str
    source: str
    reason: str
    confidence: float | None
    run_id: str
    snapshot_id: str
    evaluation_id: str | None
    plan_id: str | None
    application_id: str

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        required = (
            self.event_id,
            self.previous_vendor_mode,
            self.requested_vendor_mode,
            self.source,
            self.reason,
            self.run_id,
            self.snapshot_id,
            self.application_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("transition event fields must be explicit")
        if self.previous_vendor_mode == self.requested_vendor_mode:
            raise ValueError("a transition must change vendor mode")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


class StorageModeTransitionHistoryStore:
    """Append and read deduplicated transition events from durable JSONL."""

    def __init__(self, path: Path, *, maximum_events: int = 200) -> None:
        if maximum_events <= 0:
            raise ValueError("maximum_events must be positive")
        self._path = path
        self._maximum_events = maximum_events

    def append(self, event: StorageModeTransitionEvent) -> bool:
        """Append once by application ID; return whether a row was written."""
        if any(
            existing.application_id == event.application_id
            for existing in self.load()
        ):
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(event)
        payload["schema_version"] = 1
        payload["occurred_at"] = event.occurred_at.isoformat()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def load(self) -> tuple[StorageModeTransitionEvent, ...]:
        if not self._path.exists():
            return ()
        events: list[StorageModeTransitionEvent] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
                events.append(_deserialize_event(payload))
            except (json.JSONDecodeError, TypeError, ValueError):
                # One interrupted or legacy row must not hide valid audit rows.
                continue
        return tuple(events[-self._maximum_events :])


def _deserialize_event(payload: dict[str, Any]) -> StorageModeTransitionEvent:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported transition-history schema")
    return StorageModeTransitionEvent(
        event_id=str(payload["event_id"]),
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        previous_vendor_mode=str(payload["previous_vendor_mode"]),
        requested_vendor_mode=str(payload["requested_vendor_mode"]),
        source=str(payload["source"]),
        reason=str(payload["reason"]),
        confidence=(
            float(payload["confidence"])
            if payload.get("confidence") is not None
            else None
        ),
        run_id=str(payload["run_id"]),
        snapshot_id=str(payload["snapshot_id"]),
        evaluation_id=(
            str(payload["evaluation_id"])
            if payload.get("evaluation_id") is not None
            else None
        ),
        plan_id=(
            str(payload["plan_id"])
            if payload.get("plan_id") is not None
            else None
        ),
        application_id=str(payload["application_id"]),
    )
