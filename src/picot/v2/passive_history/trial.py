"""Optional capture-only runtime trial; no index worker or planning authority."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from .evidence import EvidenceRecorder

TRIAL_ROOT = Path("/data/picot_history_capture_trial")
TRIAL_SECONDS = 30 * 60


class HistoryCaptureTrial:
    """Owned by the runtime thread; recorder does all evidence I/O asynchronously."""

    def __init__(self, options: Mapping[str, object], *, root: Path = TRIAL_ROOT) -> None:
        self._session_id = uuid4().hex
        self._started_at = datetime.now(UTC).isoformat()
        self.recorder: EvidenceRecorder | None = None
        self.evidence_offer: Callable[[str], object] | None = None
        self._state = "disabled"
        self._offers: Counter[str] = Counter()
        self._offer_max_ms = 0.0
        self._error: str | None = None
        # Do not let a string such as "false" enable a worker.
        if options.get("history_capture_trial_enabled") is not True:
            return
        try:
            self.recorder = EvidenceRecorder(
                root,
                stop_on_failure=True,
                duration_seconds=TRIAL_SECONDS,
                total_directory_budget=True,
            )
        except Exception as exc:
            self._state = "initialization_failed"
            self._error = type(exc).__name__
            return
        self._state = "active"
        self.evidence_offer = self._offer

    def _offer(self, text: str) -> str:
        started = perf_counter()
        assert self.recorder is not None
        outcome = self.recorder.offer(text)
        self._offers[outcome] += 1
        self._offer_max_ms = max(self._offer_max_ms, (perf_counter() - started) * 1000)
        return outcome

    def report(self) -> dict[str, object]:
        status = self.recorder.status(blocking=False) if self.recorder else {}
        state = self._state
        if status:
            if status.get("failed", 0):
                state = "storage_failed"
            elif status.get("expired", 0):
                state = "expired"
            elif status.get("stopped", 0):
                state = "stopped"
        rejected = sum(count for name, count in self._offers.items() if name != "accepted")
        return {
            "state": state,
            "session_id": self._session_id,
            "started_at": self._started_at,
            "initialization_error": self._error,
            "duration_limit_seconds": TRIAL_SECONDS,
            "storage_limit_bytes": 512 * 1024**2,
            "free_reserve_bytes": 128 * 1024**2,
            "memory_reservation_limit_bytes": 64 * 1024**2,
            "record_limit_bytes": 32 * 1024**2,
            "queue_limit": 2,
            "status_available": status is not None,
            "accepted": self._offers["accepted"],
            "offer_outcomes": dict(self._offers),
            "published": status.get("published", 0) if status is not None else None,
            "rejected": rejected,
            "missed": (
                rejected + status.get("failed", 0) + status.get("discarded", 0)
                if status is not None and self._state != "initialization_failed"
                else None
            ),
            "offer_max_ms": round(self._offer_max_ms, 6),
            **(status or {}),
        }
