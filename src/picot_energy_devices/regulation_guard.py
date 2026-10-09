"""Verify offered correction only; legitimate load and mode changes are not oscillation."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from math import isfinite
from pathlib import Path


class CorrectionGuard:
    def __init__(self, *, enabled: bool, path: Path | None = None) -> None:
        self.enabled = enabled
        self.path = path
        self.latched_reason: str | None = None
        self.bad_since: datetime | None = None
        self.missing_since: datetime | None = None
        self.last_valid_measurement: datetime | None = None
        self.offers: deque[tuple[datetime, float]] = deque()
        if path is not None and path.exists():
            try:
                saved = json.loads(path.read_text())
                if not isinstance(saved, dict) or not isinstance(saved.get("reason"), str):
                    raise ValueError("invalid guard state")
                self.latched_reason = saved["reason"]
            except (OSError, ValueError):
                self.latched_reason = "guard_state_unreadable"
        if not enabled:
            self.latched_reason = None
            if path is not None and path.exists():
                path.unlink()

    def latch(self, reason: str) -> None:
        self.latched_reason = reason
        if self.path is not None:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"reason": reason}))
            temporary.replace(self.path)

    def check(self, *, result: dict[str, object], offered_w: float | None,
              now: datetime) -> dict[str, object]:
        candidate = result.get("candidate_w")
        expected = self.offers
        while expected and (now - expected[0][0]).total_seconds() > 5:
            expected.popleft()
        # Compare the received P1 against earlier transmitted candidates, not
        # against the latest RAW value while appliances/EV/PV change underneath.
        usable = offered_w is not None and isfinite(offered_w)
        matched = (offered_w is not None and usable
                   and any(abs(offered_w - value) <= 50 for _, value in expected))
        comparable = bool(expected)
        if result.get("status") == "ready":
            stamp = result.get("source_measured_at")
            if isinstance(stamp, str):
                try:
                    measured = datetime.fromisoformat(stamp)
                    if measured.tzinfo is not None and measured <= now:
                        self.last_valid_measurement = measured
                except ValueError:
                    pass
        if self.enabled and self.latched_reason is None:
            if result.get("status") != "ready" or not usable:
                # Match the hold deadline: an already ageing last-good source
                # must not start another ten-second grace period on detection.
                start = ((self.last_valid_measurement
                          if result.get("status") != "ready" else None) or now)
                self.missing_since = self.missing_since or start
                if (now - self.missing_since).total_seconds() >= 10:
                    self.latch("persistent_measurement_loss")
            else:
                self.missing_since = None
            if comparable and usable:
                if matched:
                    self.bad_since = None
                else:
                    self.bad_since = self.bad_since or now
                    if (now - self.bad_since).total_seconds() >= 30:
                        self.latch("offered_correction_mismatch")
            elif not comparable:
                self.bad_since = None
        if (result.get("status") == "ready" and not isinstance(candidate, bool)
                and isinstance(candidate, (int, float)) and isfinite(candidate)):
            expected.append((now, float(candidate)))
        result = dict(result, correction_guard=(
            "disabled" if not self.enabled else "latched" if self.latched_reason else
            "matched" if matched else "checking"
        ), offered_p1_w=offered_w if usable else None,
            correction_source_reason=result.get("reason"), correction_tolerance_w=50,
            correction_transfer_seconds=5, correction_mismatch_seconds=30,
            measurement_loss_seconds=10)
        if self.enabled and self.latched_reason:
            result.update(status="blocked", candidate_w=None,
                          reason=self.latched_reason, fallback="latched_raw_fallback")
        return result
