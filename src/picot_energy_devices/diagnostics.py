"""Independent bounded telemetry writer and consistent read-only ZIP export."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from picot_energy_devices import __version__

SETTINGS = {
    "regulation_api_enabled", "regulation_control_enabled", "regulation_shadow_enabled",
    "regulation_raw_entity", "regulation_battery_entity", "regulation_ev_entity",
    "regulation_offered_entity", "ev_sessions_enabled", "ev_power_entity", "ev_switch_entity",
    "poll_interval_seconds",
}
FIELDS = {
    "raw_grid_w", "battery_w", "ev_w", "intended_candidate_w", "candidate_w",
    "ev_switch_state", "offered_p1_w", "excluded_ev_w", "permitted_net_demand_w", "evaluated_at",
    "source_measured_at", "source_ages_seconds", "source_skew_seconds",
    "battery_report_age_seconds", "raw_measured_at", "battery_measured_at", "ev_measured_at",
    "status", "reason", "fallback", "holding_measurement", "correction_guard",
    "correction_source_reason", "source_failure_entity", "ev_measurement_source",
    "control_enabled", "measured_at", "revision", "correction_tolerance_w",
    "correction_transfer_seconds", "correction_mismatch_seconds", "measurement_loss_seconds",
    "latched_at", "latched_origin", "consumer_source", "consumer_measured_at",
    "consumer_reported_at", "consumer_fallback_active", "quantization_w", "update_dead_band_w",
}
SESSION_FIELDS = {
    "session_id", "version", "state", "switch_state", "current_power_w",
    "last_measured_at", "measurement_available", "measurement_complete",
    "error", "completion_reason", "interruption_reason", "owns_switch", "confirmed",
    "expected_duration_seconds", "remaining_duration_seconds", "delivered_energy_wh",
    "remaining_energy_wh", "planned_start", "planned_end", "measured_at", "expected_power_w",
}


class DiagnosticsRecorder:
    """Logging uses its own queue/database; overload drops telemetry, never delays control."""

    def __init__(self, path: Path, *, options: dict[str, object]) -> None:
        self.path = path.resolve()
        self.options = {k: v for k, v in options.items() if k in SETTINGS}
        self.queue: Queue[tuple[float, str, dict[str, object]]] = Queue(maxsize=1024)
        self.stop = Event()
        self.lock = Lock()
        self.dropped = 0
        self.last_error: str | None = None
        self.started_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS samples ("
                       "bucket INTEGER, kind TEXT, stamp REAL, payload TEXT, "
                       "PRIMARY KEY(bucket, kind))")
            db.execute("CREATE TABLE IF NOT EXISTS events ("
                       "id INTEGER PRIMARY KEY, stamp REAL, kind TEXT, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS state (kind TEXT PRIMARY KEY, signature TEXT)")
        self.thread = Thread(target=self._run, name="energy-diagnostics", daemon=True)
        self.thread.start()
        self.record("startup", {"version": __version__, "settings": self.options})

    def record(self, kind: str, payload: dict[str, object], *, now: datetime | None = None) -> None:
        when = now or datetime.now(UTC)
        if kind == "regulation":
            data = {k: v for k, v in payload.items() if k in FIELDS}
        elif kind == "ev":
            session = payload.get("session")
            data = {"generated_at": payload.get("generated_at"),
                    "ev_w": payload.get("ev_w"),
                    "ev_measured_at": payload.get("ev_measured_at"),
                    "ev_switch_state": payload.get("ev_switch_state"),
                    "session": ({k: v for k, v in session.items() if k in SESSION_FIELDS}
                                if isinstance(session, dict) else None)}
        elif kind == "startup":
            data = {"version": __version__, "settings": self.options}
        else:
            return
        try:
            self.queue.put_nowait((when.timestamp(), kind, data))
        except Full:
            with self.lock:
                self.dropped += 1

    def _run(self) -> None:
        last_cleanup = 0.0
        last_health: tuple[int, str | None] = (0, None)
        while not self.stop.is_set() or not self.queue.empty():
            try:
                stamp, kind, payload = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                with sqlite3.connect(self.path, timeout=0.1) as db:
                    serialized = json.dumps(payload, allow_nan=False, separators=(",", ":"))
                    if kind != "startup":
                        db.execute("INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?)",
                                   (int(stamp), kind, stamp, serialized))
                    if kind == "regulation":
                        signature: object = [payload.get(k) for k in (
                            "control_enabled", "status", "reason", "fallback",
                            "holding_measurement", "latched_at", "source_failure_entity",
                            "consumer_source", "consumer_fallback_active", "ev_switch_state",
                        )]
                    elif kind == "ev":
                        session = payload.get("session")
                        signature = ([session.get(k) for k in
                                      ("session_id", "state", "switch_state",
                                       "measurement_available", "error")]
                                     if isinstance(session, dict)
                                     else payload.get("ev_switch_state"))
                    else:
                        signature = None
                    encoded_signature = json.dumps(signature, separators=(",", ":"))
                    previous = db.execute("SELECT signature FROM state WHERE kind=?", (kind,)
                                          ).fetchone()
                    if kind == "startup" or previous is None or previous[0] != encoded_signature:
                        db.execute("INSERT INTO events(stamp, kind, payload) VALUES (?, ?, ?)",
                                   (stamp, kind, serialized))
                        db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)",
                                   (kind, encoded_signature))
                    with self.lock:
                        health = (self.dropped, self.last_error)
                    if health != last_health:
                        db.execute("INSERT INTO events(stamp, kind, payload) VALUES (?, ?, ?)",
                                   (stamp, "logging_health", json.dumps({
                                       "dropped_records": health[0], "last_write_error": health[1],
                                       "process_started_at": self.started_at,
                                   })))
                        last_health = health
                    if stamp - last_cleanup >= 300:
                        db.execute("DELETE FROM samples WHERE stamp < ?", (stamp - 48 * 3600,))
                        last_cleanup = stamp
            except (OSError, ValueError, TypeError, sqlite3.Error) as error:
                with self.lock:
                    self.dropped += 1
                    self.last_error = str(error)
            finally:
                self.queue.task_done()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)

    def export_zip(self, *, now: datetime | None = None) -> bytes:
        when = now or datetime.now(UTC)
        cutoff = when.timestamp() - 48 * 3600
        with self.lock:
            health = {"dropped_records": self.dropped, "last_write_error": self.last_error,
                      "pending_records": self.queue.qsize(), "counters_scope": "current_process",
                      "process_started_at": self.started_at}
        buffer = io.BytesIO()
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=0.2) as db:
            # Read all tables at the same point in time, without locking the WAL writer.
            db.execute("BEGIN")
            rows = db.execute("SELECT kind, count(*), min(stamp), max(stamp) FROM samples "
                              "WHERE stamp >= ? GROUP BY kind", (cutoff,)).fetchall()
            manifest = {"schema_version": 1, "version": __version__,
                        "exported_at": when.isoformat(), "retention_hours": 48,
                        "nominal_sample_interval_seconds": 1, "observer_only": True,
                        "settings": self.options, "logging_health": health,
                        "coverage": [{"kind": r[0], "count": r[1],
                                      "first_at": datetime.fromtimestamp(r[2], UTC).isoformat(),
                                      "last_at": datetime.fromtimestamp(r[3], UTC).isoformat()}
                                     for r in rows]}
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, allow_nan=False))
                for filename, query, args in [
                    ("measurements.jsonl", "SELECT stamp, kind, payload FROM samples "
                     "WHERE stamp >= ? ORDER BY stamp, kind", (cutoff,)),
                    ("events.jsonl", "SELECT stamp, kind, payload FROM events ORDER BY id", ()),
                ]:
                    with archive.open(filename, "w") as output:
                        for stamp, kind, payload in db.execute(query, args):
                            row = {"recorded_at": datetime.fromtimestamp(stamp, UTC).isoformat(),
                                   "kind": kind, "data": json.loads(payload)}
                            output.write((json.dumps(row, separators=(",", ":")) + "\n").encode())
                archive.writestr("README.txt", "Energy Devices observer diagnostics.\n"
                                 "Measurements: latest 48 hours, up to one record/second/kind.\n"
                                 "Events persist independently of sample retention.\n"
                                 "Recording timestamps are not physical measurement timestamps.\n"
                                 "Check coverage, gaps and logging_health.\n"
                                 "Battery values use the configured source.\n"
                                 "No measurements before installation are reconstructed.\n")
        return buffer.getvalue()
