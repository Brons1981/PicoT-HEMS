"""Measured EV regulation policy and read-only API; no storage commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from http.server import ThreadingHTTPServer
from math import ceil, floor, isfinite

from picot_energy_devices.home_assistant import HomeAssistantClient


@dataclass(frozen=True)
class PowerReport:
    watts: float
    reported_at: datetime

    @classmethod
    def from_state(cls, payload: dict[str, object]) -> PowerReport:
        # A fetch time and last_changed do not establish source freshness.
        raw = payload.get("last_reported")
        if not isinstance(raw, str):
            raise ValueError("source report time missing")
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("source report time must include timezone")
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict) or attributes.get("unit_of_measurement") not in {
            "W",
            "kW",
        }:
            raise ValueError("explicit power unit required")
        return cls(HomeAssistantClient.measurement(payload, quantity="power"), stamp)


def regulation_candidate(
    raw: PowerReport,
    battery: PowerReport,
    ev: PowerReport,
    *,
    now: datetime,
    maximum_age_seconds: float = 3.0,
    maximum_skew_seconds: float = 2.0,
    quantization_w: float = 20.0,
) -> dict[str, object]:
    """Produce a measured candidate. Blocked output has no usable control value.

    Battery sign: positive charge, negative discharge. Quantization rounds
    permitted charging/discharging towards zero, avoiding additional support.
    This preserves source steps rather than averaging them in time.
    """
    if now.tzinfo is None:
        raise ValueError("evaluation time must include timezone")
    if (
        not all(isfinite(v) for v in (maximum_age_seconds, maximum_skew_seconds, quantization_w))
        or maximum_age_seconds <= 0
        or maximum_skew_seconds < 0
        or quantization_w < 0
    ):
        raise ValueError("invalid regulation bounds")
    reports = (raw, battery, ev)
    if any(not isfinite(r.watts) or r.reported_at.tzinfo is None for r in reports):
        raise ValueError("invalid source report")
    ages = [(now - source.reported_at).total_seconds() for source in reports]
    skew = max(r.reported_at for r in reports) - min(r.reported_at for r in reports)
    reason = (
        "future_report"
        if min(ages) < 0
        else "stale_source"
        if max(ages) > maximum_age_seconds
        else "source_time_skew"
        if skew.total_seconds() > maximum_skew_seconds
        else "negative_ev_power"
        if ev.watts < 0
        else None
    )
    result: dict[str, object] = {
        "observer_only": True,
        "actuation_authority": False,
        "raw_grid_w": raw.watts,
        "battery_w": battery.watts,
        "ev_w": ev.watts,
        "source_ages_seconds": ages,
        "source_skew_seconds": skew.total_seconds(),
        "evaluated_at": now.isoformat(),
        "source_measured_at": min(r.reported_at for r in reports).isoformat(),
        "candidate_w": None,
        "status": "blocked" if reason else "ready",
        "reason": reason,
        "fallback": "no_control_value" if reason else "none",
    }
    if reason:
        return result
    demand = raw.watts - battery.watts
    if not isfinite(demand):
        result.update(
            {"status": "blocked", "reason": "invalid_balance", "fallback": "no_control_value"}
        )
        return result
    ev_exclusion = min(ev.watts, max(0.0, demand))
    permitted = demand - ev_exclusion
    if ev.watts > 0 and quantization_w:
        steps = permitted / quantization_w
        permitted = (floor(steps) if steps >= 0 else ceil(steps)) * quantization_w
    result.update(
        {
            "candidate_w": battery.watts + permitted,
            "excluded_ev_w": ev_exclusion,
            "permitted_net_demand_w": permitted,
            "quantization_w": quantization_w if ev.watts > 0 else 0.0,
        }
    )
    return result


class RegulationObserver:
    """Conservative update dead band on demand, not a second actuator loop."""

    def __init__(self) -> None:
        self._previous_demand: float | None = None

    def reset(self) -> None:
        self._previous_demand = None

    def evaluate(
        self,
        raw: PowerReport,
        battery: PowerReport,
        ev: PowerReport,
        *,
        now: datetime,
    ) -> dict[str, object]:
        result = regulation_candidate(raw, battery, ev, now=now)
        if result["status"] != "ready" or ev.watts == 0:
            self._previous_demand = None
            return result
        demand = result["permitted_net_demand_w"]
        assert isinstance(demand, (int, float))
        previous = self._previous_demand
        # Reduction towards neutral and sign changes always pass immediately.
        # Hold only a small increase away from neutral, never a larger output.
        if (
            previous is not None
            and previous * demand > 0
            and 0 < abs(demand) - abs(previous) <= 20.0
        ):
            demand = previous
        self._previous_demand = demand
        result["permitted_net_demand_w"] = demand
        result["candidate_w"] = battery.watts + demand
        result["update_dead_band_w"] = 20.0
        return result


class RegulationSnapshotStore:
    """Short-lived, fail-closed HTTP snapshot; no actuator dispatch."""

    def __init__(self, *, control_enabled: bool) -> None:
        from threading import Lock

        self._lock = Lock()
        self._snapshot: dict[str, object] = {}
        self._consecutive_ready = 0
        self._revision = 0
        self.control_enabled = control_enabled

    def update(self, result: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self._revision += 1
            self._consecutive_ready = (
                self._consecutive_ready + 1 if result.get("status") == "ready" else 0
            )
            snapshot = dict(result)
            if self.control_enabled and self._consecutive_ready < 3:
                snapshot.update(
                    status="blocked", reason="awaiting_three_fresh_reports", candidate_w=None
                )
            snapshot.update(
                contract="measured-external-load-support-policy:v1",
                control_enabled=self.control_enabled,
                observer_only=not self.control_enabled,
                regulation_authority=self.control_enabled,
                source_id="energy-devices:ev-regulation",
                revision=str(self._revision),
                measured_at=result.get("source_measured_at", result.get("evaluated_at")),
            )
            self._snapshot = snapshot
            return dict(snapshot)

    def read(self, *, now: datetime) -> dict[str, object] | None:
        with self._lock:
            result = dict(self._snapshot)
        stamp = result.get("evaluated_at")
        if not isinstance(stamp, str) or result.get("status") != "ready":
            return None
        age = (now - datetime.fromisoformat(stamp)).total_seconds()
        ages = result.get("source_ages_seconds")
        if (
            not isinstance(ages, list)
            or not 0 <= age <= 3
            or any(not isinstance(a, (int, float)) or a + age > 3 for a in ages)
        ):
            return None
        value = result.get("candidate_w") if self.control_enabled else result.get("raw_grid_w")
        return dict(result, total_act_power=value)


def create_regulation_api(
    store: RegulationSnapshotStore, *, host: str, port: int,
) -> ThreadingHTTPServer:
    """Shelly-compatible read-only endpoint; failures return HTTP503, never zero."""
    import json
    from datetime import UTC
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] != "/rpc/EM.GetStatus":
                self.send_error(404)
                return
            result = store.read(now=datetime.now(UTC))
            if result is None:
                self.send_error(503, "regulation sources unavailable")
                return
            data = json.dumps(result, allow_nan=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)
