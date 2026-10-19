"""Read-only startup milestones, independent of expensive dashboard publication."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import RLock
from time import monotonic


class StartupProgress:
    """Track completed milestones, not an estimate of remaining wall-clock time."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = RLock()
        self._started = self._phase_started = clock()
        self._finished: float | None = None
        self._state = "starting"
        self._phase = "initializing"
        self._label = "Instellingen en historie voorbereiden"
        self._percent = 0

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            now = self._finished if self._finished is not None else self._clock()
            return {
                "state": self._state, "phase": self._phase, "label": self._label,
                "percent": self._percent,
                "elapsed_seconds": round(max(0.0, now - self._started), 1),
                "phase_elapsed_seconds": round(max(0.0, now - self._phase_started), 1),
            }

    def _log_phase(self, now: float) -> None:
        print(json.dumps({
            "event": "picot_v2_startup_phase", "phase": self._phase,
            "state": self._state,
            "duration_ms": round((now - self._phase_started) * 1000, 3),
            "elapsed_ms": round((now - self._started) * 1000, 3),
        }), flush=True)

    def enter(self, phase: str, label: str, percent: int) -> None:
        with self._lock:
            if self._state == "ready":
                return
            now = self._clock()
            self._log_phase(now)
            self._phase_started = now
            self._state, self._phase, self._label = "starting", phase, label
            self._percent = max(self._percent, min(99, max(0, percent)))

    def complete(self) -> None:
        with self._lock:
            if self._state == "ready":
                return
            now = self._clock()
            self._log_phase(now)
            self._finished = now
            self._state, self._phase, self._label = "ready", "ready", "Dashboard gereed"
            self._percent = 100

    def fail(self) -> None:
        with self._lock:
            if self._state != "ready":
                self._state = "failed"
                self._log_phase(self._clock())

    @contextmanager
    def stage(self, phase: str, label: str, percent: int) -> Iterator[None]:
        """Restore the outer phase after nested fresh-input checkpoints."""
        with self._lock:
            previous = (self._phase, self._label, self._percent)
        self.enter(phase, label, percent)
        try:
            yield
        except Exception:
            self.fail()
            raise
        else:
            self.enter(*previous)
