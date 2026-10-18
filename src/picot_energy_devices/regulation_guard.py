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
        self.latched_at: str | None = None
        self.latched_origin: dict[str, object] | None = None
        self.missing_origin: dict[str, object] | None = None
        self.mismatch_origin: dict[str, object] | None = None
        self.recovery_since: datetime | None = None
        self.recovery_previous: datetime | None = None
        self.recovery_probe: datetime | None = None
        self.recovery_matches = 0
        self.recovery_consumer_at: datetime | None = None
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
                self.latched_at = saved.get("latched_at")
                self.latched_origin = saved.get("origin")
            except (OSError, ValueError):
                self.latched_reason = "guard_state_unreadable"
        if not enabled:
            self.latched_reason = None
            self.latched_at = None
            self.latched_origin = None
            if path is not None and path.exists():
                path.unlink()

    def latch(self, reason: str, *, now: datetime | None = None,
              origin: dict[str, object] | None = None) -> None:
        self.latched_reason = reason
        self.latched_at = now.isoformat() if now is not None else None
        self.latched_origin = origin
        if self.path is not None:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"reason": reason, "latched_at": self.latched_at,
                                             "origin": self.latched_origin}))
            temporary.replace(self.path)

    def _recover(self, result: dict[str, object], *, usable: bool,
                 matched: bool, now: datetime) -> bool:
        """Retry transient loss only; keep the persisted latch until delivery is proven."""
        if not self.enabled or self.latched_reason != "persistent_measurement_loss":
            return False
        stamp = result.get("source_measured_at")
        measured = None
        if isinstance(stamp, str):
            try:
                measured = datetime.fromisoformat(stamp)
            except ValueError:
                pass
        valid = (result.get("status") == "ready" and usable and measured is not None
                 and measured.tzinfo is not None
                 and 0 <= (now - measured).total_seconds() <= 3)
        continuous = (self.recovery_previous is None or
                      0 < (now - self.recovery_previous).total_seconds() <= 3)
        if not valid or not continuous:
            self.recovery_since = self.recovery_probe = None
            self.recovery_matches = 0
            self.offers.clear()
        self.recovery_previous = now
        if not valid:
            return False
        self.recovery_since = self.recovery_since or now
        if (now - self.recovery_since).total_seconds() < 10:
            return False
        if self.recovery_probe is None:
            self.recovery_probe = now
            self.offers.clear()  # Shadow candidates were never transmitted.
            return True
        consumer_stamp = result.get("consumer_reported_at")
        consumer_fresh = False
        reported = None
        if isinstance(consumer_stamp, str):
            try:
                reported = datetime.fromisoformat(consumer_stamp)
                consumer_fresh = (reported.tzinfo is not None
                                  and 0 <= (now - reported).total_seconds() <= 3)
            except ValueError:
                pass
        confirmed = (matched and consumer_fresh and reported is not None
                     and (self.recovery_consumer_at is None or reported > self.recovery_consumer_at)
                     and result.get("consumer_fallback_active") is False)
        self.recovery_consumer_at = reported
        self.recovery_matches = self.recovery_matches + 1 if confirmed else 0
        if self.recovery_matches >= 3:
            if self.path is not None:
                self.path.unlink(missing_ok=True)
            self.latched_reason = self.latched_at = self.latched_origin = None
            self.missing_since = self.bad_since = None
            self.missing_origin = self.mismatch_origin = None
            self.recovery_since = self.recovery_probe = None
            self.recovery_matches = 0
            return False
        if (now - self.recovery_probe).total_seconds() >= 10:
            self.recovery_since = self.recovery_probe = None
            self.recovery_matches = 0
            self.offers.clear()
            return False
        return True

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
        recovering = self._recover(result, usable=usable, matched=matched, now=now)
        if self.enabled and self.latched_reason is None:
            if result.get("status") != "ready" or not usable:
                # Match the hold deadline: an already ageing last-good source
                # must not start another ten-second grace period on detection.
                start = ((self.last_valid_measurement
                          if result.get("status") != "ready" else None) or now)
                self.missing_since = self.missing_since or start
                if self.missing_origin is None:
                    self.missing_origin = {
                        "detected_at": now.isoformat(),
                        "reason": result.get("reason") or "offered_p1_unavailable",
                        "source_failure_entity": result.get("source_failure_entity"),
                        "source_measured_at": result.get("source_measured_at"),
                        "raw_measured_at": result.get("raw_measured_at"),
                        "battery_measured_at": result.get("battery_measured_at"),
                        "ev_measured_at": result.get("ev_measured_at"),
                        "source_ages_seconds": result.get("source_ages_seconds"),
                        "raw_grid_w": result.get("raw_grid_w"),
                        "battery_w": result.get("battery_w"), "ev_w": result.get("ev_w"),
                    }
                if (now - self.missing_since).total_seconds() >= 10:
                    self.latch("persistent_measurement_loss", now=now, origin=self.missing_origin)
            else:
                self.missing_since = None
                self.missing_origin = None
            if comparable and usable:
                if matched:
                    self.bad_since = None
                    self.mismatch_origin = None
                else:
                    self.bad_since = self.bad_since or now
                    if self.mismatch_origin is None:
                        self.mismatch_origin = {"detected_at": now.isoformat(),
                                               "reason": "offered_correction_mismatch",
                                               "offered_p1_w": offered_w,
                                               "expected_candidates_w": [v for _, v in expected]}
                    if (now - self.bad_since).total_seconds() >= 30:
                        self.latch("offered_correction_mismatch", now=now,
                                   origin=self.mismatch_origin)
            elif not comparable:
                self.bad_since = None
                self.mismatch_origin = None
        if (result.get("status") == "ready" and not isinstance(candidate, bool)
                and isinstance(candidate, (int, float)) and isfinite(candidate)):
            expected.append((now, float(candidate)))
        result = dict(result, correction_guard=(
            "disabled" if not self.enabled else "recovering" if recovering else
            "latched" if self.latched_reason else
            "matched" if matched else "checking"
        ), offered_p1_w=offered_w if usable else None,
            correction_source_reason=result.get("reason"), correction_tolerance_w=50,
            correction_transfer_seconds=5, correction_mismatch_seconds=30,
            measurement_loss_seconds=10, latched_at=self.latched_at,
            latched_origin=self.latched_origin)
        if recovering:
            result.update(reason="verifying_correction_recovery")
        if self.enabled and self.latched_reason and not recovering:
            result.update(status="blocked", candidate_w=None,
                          reason=self.latched_reason, fallback="latched_raw_fallback")
        return result
