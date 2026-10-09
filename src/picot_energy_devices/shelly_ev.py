"""Shared, read-only local Shelly EV observation; no actuator or HA credentials."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from threading import RLock
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from picot_energy_devices.regulation import PowerReport


@dataclass(frozen=True)
class ShellyEVObservation:
    power: PowerReport
    output: bool
    switch_changed_at: datetime
    energy_wh: float


class ShellyEVSource:
    """One local poller shared by sessions and regulation, preserving observation time."""

    def __init__(self, url: str) -> None:
        parts = urlsplit(url)
        if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
                or parts.path != "/rpc/Switch.GetStatus" or parts.query != "id=0"
                or parts.fragment):
            raise ValueError("EV URL must be http://HOST/rpc/Switch.GetStatus?id=0")
        self.url = url
        self.lock = RLock()
        self.observation: ShellyEVObservation | None = None
        self.error = "ev_local_api_not_observed"
        self.previous_output: bool | None = None
        self.changed_at: datetime | None = None

    def poll_once(self) -> None:
        started = datetime.now(UTC)
        try:
            # Timestamp is the request start, not a renewed timestamp on cache reads.
            # A successful response is local observation evidence, not a device sample clock.
            with urlopen(Request(self.url), timeout=2) as response:
                if response.geturl() != self.url:
                    raise ValueError("EV local API redirect is not supported")
                raw = response.read(8193)
            if len(raw) > 8192:
                raise ValueError("EV local API response too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("id") != 0:
                raise ValueError("EV local API invalid channel")
            output, power = payload.get("output"), payload.get("apower")
            energy = payload.get("aenergy")
            total = energy.get("total") if isinstance(energy, dict) else None
            if (not isinstance(output, bool) or isinstance(power, bool)
                    or not isinstance(power, (int, float)) or not isfinite(power) or power < 0
                    or isinstance(total, bool) or not isinstance(total, (int, float))
                    or not isfinite(total) or total < 0):
                raise ValueError("EV local API invalid power, output or energy")
            if not output and power != 0:
                raise ValueError("EV local API inconsistent off/power observation")
            if (datetime.now(UTC) - started).total_seconds() > 3:
                raise ValueError("EV local API response too old")
            with self.lock:
                if output != self.previous_output or self.changed_at is None:
                    self.changed_at = started
                self.previous_output = output
                self.observation = ShellyEVObservation(
                    PowerReport(float(power), started), output, self.changed_at, float(total)
                )
                self.error = ""
        except (OSError, ValueError) as error:
            with self.lock:
                self.observation = None
                self.error = "ev_local_api_unavailable: " + str(error)[:180]

    def read(self) -> ShellyEVObservation:
        with self.lock:
            observation = self.observation
            if observation is None:
                raise ValueError(self.error)
            age = (datetime.now(UTC) - observation.power.reported_at).total_seconds()
            if not 0 <= age <= 3:
                raise ValueError("ev_local_api_stale")
            return observation

    def run(self) -> None:
        while True:
            started = time.perf_counter()
            self.poll_once()
            time.sleep(max(0.0, 1 - (time.perf_counter() - started)))
