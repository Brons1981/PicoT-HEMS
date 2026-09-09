"""SQLite registry, observations and learned session profiles."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from statistics import median

from picot_energy_devices import recordings
from picot_energy_devices.contracts import (
    CATALOG_SCHEMA_VERSION,
    PROFILE_METHOD_VERSION,
    DeviceDefinition,
    DeviceObservation,
)


class EnergyDeviceStore:
    """Own device evidence without importing or depending on PicoT."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] | None = None,
        maximum_sample_gap_seconds: float = 300.0,
    ) -> None:
        self._path = path
        self._now = now or (lambda: datetime.now(UTC))
        self._maximum_sample_gap_seconds = maximum_sample_gap_seconds
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    power_entity_id TEXT NOT NULL UNIQUE,
                    energy_entity_id TEXT,
                    active_threshold_w REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS samples (
                    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    power_w REAL NOT NULL,
                    energy_meter_wh REAL,
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );
                CREATE INDEX IF NOT EXISTS samples_device_time
                    ON samples(device_id, observed_at);
                CREATE TABLE IF NOT EXISTS active_sessions (
                    device_id TEXT PRIMARY KEY,
                    starts_at TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    last_power_w REAL NOT NULL,
                    integrated_energy_wh REAL NOT NULL,
                    energy_meter_start_wh REAL,
                    peak_power_w REAL NOT NULL,
                    sample_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    energy_wh REAL NOT NULL,
                    average_power_w REAL NOT NULL,
                    peak_power_w REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );
                CREATE INDEX IF NOT EXISTS sessions_device_end
                    ON sessions(device_id, ends_at);
                CREATE TABLE IF NOT EXISTS latest_status (
                    device_id TEXT PRIMARY KEY,
                    availability TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    power_w REAL,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('revision', 1);
                """
            )

            connection.executescript(recordings.SCHEMA)

    @staticmethod
    def _definition(row: sqlite3.Row) -> DeviceDefinition:
        energy_entity = row["energy_entity_id"]
        return DeviceDefinition(
            device_id=str(row["device_id"]),
            name=str(row["name"]),
            power_entity_id=str(row["power_entity_id"]),
            energy_entity_id=(str(energy_entity) if energy_entity is not None else None),
            active_threshold_w=float(row["active_threshold_w"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _increment_revision(self, connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE metadata SET value = value + 1 WHERE key = 'revision'")

    def add_device(
        self,
        *,
        name: str,
        power_entity_id: str,
        energy_entity_id: str | None = None,
        active_threshold_w: float = 20.0,
    ) -> DeviceDefinition:
        timestamp = self._now()
        normalized_power = power_entity_id.strip()
        normalized_energy = energy_entity_id.strip() if energy_entity_id else None
        device = DeviceDefinition(
            device_id=f"energy-device-{sha256(normalized_power.encode()).hexdigest()[:16]}",
            name=name.strip(),
            power_entity_id=normalized_power,
            energy_entity_id=normalized_energy,
            active_threshold_w=float(active_threshold_w),
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM devices WHERE power_entity_id = ?",
                (device.power_entity_id,),
            ).fetchone()
            created_at = (
                str(existing["created_at"])
                if existing is not None
                else timestamp.isoformat()
            )
            connection.execute(
                """
                INSERT INTO devices(
                    device_id, name, power_entity_id, energy_entity_id,
                    active_threshold_w, created_at, updated_at, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(power_entity_id) DO UPDATE SET
                    name=excluded.name,
                    energy_entity_id=excluded.energy_entity_id,
                    active_threshold_w=excluded.active_threshold_w,
                    updated_at=excluded.updated_at,
                    enabled=1
                """,
                (
                    device.device_id,
                    device.name,
                    device.power_entity_id,
                    device.energy_entity_id,
                    device.active_threshold_w,
                    created_at,
                    timestamp.isoformat(),
                ),
            )
            self._increment_revision(connection)
            row = connection.execute(
                "SELECT * FROM devices WHERE power_entity_id = ?",
                (device.power_entity_id,),
            ).fetchone()
        assert row is not None
        return self._definition(row)

    def disable_device(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM recordings WHERE device_id=? AND ends_at IS NULL", (device_id,)
            ).fetchone():
                raise ValueError("Rond de opname eerst af of verwijder deze")
            cursor = connection.execute(
                "UPDATE devices SET enabled = 0, updated_at = ? WHERE device_id = ?",
                (self._now().isoformat(), device_id.strip()),
            )
            if cursor.rowcount != 1:
                raise ValueError("unknown device")
            connection.execute("DELETE FROM active_sessions WHERE device_id = ?", (device_id,))
            self._increment_revision(connection)

    def devices(self) -> tuple[DeviceDefinition, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM devices WHERE enabled = 1 ORDER BY name, device_id"
            ).fetchall()
        return tuple(self._definition(row) for row in rows)

    def record_unavailable(self, device_id: str, error: str, *, observed_at: datetime) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO latest_status(device_id, availability, observed_at, power_w, error)
                VALUES (?, 'unavailable', ?, NULL, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    availability='unavailable', observed_at=excluded.observed_at,
                    power_w=NULL, error=excluded.error
                """,
                (device_id, observed_at.isoformat(), error[:240]),
            )

            recordings.append_sample(connection, device_id, observed_at, None, error=error[:240])

    def record_observation(self, device_id: str, observation: DeviceObservation) -> None:
        with self._connect() as connection:
            device = connection.execute(
                "SELECT active_threshold_w FROM devices WHERE device_id = ? AND enabled = 1",
                (device_id,),
            ).fetchone()
            if device is None:
                raise ValueError("unknown device")
            connection.execute(
                """
                INSERT INTO samples(device_id, observed_at, power_w, energy_meter_wh)
                VALUES (?, ?, ?, ?)
                """,
                (
                    device_id,
                    observation.observed_at.isoformat(),
                    observation.power_w,
                    observation.energy_meter_wh,
                ),
            )
            connection.execute(
                """
                INSERT INTO latest_status(device_id, availability, observed_at, power_w, error)
                VALUES (?, 'available', ?, ?, NULL)
                ON CONFLICT(device_id) DO UPDATE SET
                    availability='available', observed_at=excluded.observed_at,
                    power_w=excluded.power_w, error=NULL
                """,
                (device_id, observation.observed_at.isoformat(), observation.power_w),
            )
            recordings.append_sample(
                connection, device_id, observation.observed_at,
                observation.power_w, observation.energy_meter_wh,
            )

    def start_recording(self, device_id: str, name: str) -> None:
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Geef de opname een naam van maximaal 120 tekens")
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM devices WHERE device_id=? AND enabled=1", (device_id,)
            ).fetchone():
                raise ValueError("Onbekend apparaat")
            if connection.execute(
                "SELECT 1 FROM recordings WHERE device_id=? AND ends_at IS NULL", (device_id,)
            ).fetchone():
                raise ValueError("Er loopt al een opname voor dit apparaat")
            connection.execute(
                "INSERT INTO recordings(device_id,name,starts_at) VALUES (?,?,?)",
                (device_id, name, now.isoformat()),
            )
            status = connection.execute(
                "SELECT * FROM latest_status WHERE device_id=?", (device_id,)
            ).fetchone()
            power = None
            if status is not None and status["availability"] == "available":
                age = (now - datetime.fromisoformat(status["observed_at"])).total_seconds()
                if 0 <= age <= self._maximum_sample_gap_seconds:
                    power = float(status["power_w"])
            recordings.append_sample(connection, device_id, now, power,
                                     error="start_boundary_held_last_reading" if power is not None
                                     else "no_fresh_start_measurement")
            self._increment_revision(connection)

    def finish_recording(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            recordings.finish(connection, device_id, self._now(), self._maximum_sample_gap_seconds)
            self._increment_revision(connection)

    def recording_list(self, device_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM recordings WHERE device_id=? ORDER BY recording_id DESC",
                (device_id,),
            )]

    def recording_detail(self, recording_id: int) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM recordings WHERE recording_id=?", (recording_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Onbekende opname")
            return {**dict(row), "samples": [dict(item) for item in connection.execute(
                "SELECT * FROM recording_samples WHERE recording_id=? ORDER BY observed_at",
                (recording_id,),
            )], "maximum_sample_gap_seconds": self._maximum_sample_gap_seconds}

    def rename_recording(self, recording_id: int, name: str) -> None:
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Geef de opname een naam van maximaal 120 tekens")
        with self._connect() as connection:
            if connection.execute("UPDATE recordings SET name=? WHERE recording_id=?",
                                  (name, recording_id)).rowcount != 1:
                raise ValueError("Onbekende opname")
            self._increment_revision(connection)

    def delete_recording(self, recording_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM recording_samples WHERE recording_id=?", (recording_id,)
            )
            if connection.execute("DELETE FROM recordings WHERE recording_id=?",
                                  (recording_id,)).rowcount != 1:
                raise ValueError("Onbekende opname")
            self._increment_revision(connection)

    def clear_legacy_sessions(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE device_id=?", (device_id,))
            connection.execute("DELETE FROM active_sessions WHERE device_id=?", (device_id,))
            self._increment_revision(connection)

    def catalog(self) -> dict[str, object]:
        cards: list[dict[str, object]] = []
        with self._connect() as connection:
            revision_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'revision'"
            ).fetchone()
            for device in self.devices():
                status = connection.execute(
                    "SELECT * FROM latest_status WHERE device_id = ?",
                    (device.device_id,),
                ).fetchone()
                active = connection.execute(
                    "SELECT * FROM recordings WHERE device_id = ? AND ends_at IS NULL",
                    (device.device_id,),
                ).fetchone()
                sessions = connection.execute(
                    """
                    SELECT duration_seconds, observed_energy_wh AS energy_wh,
                        observed_energy_wh * 3600 / duration_seconds AS average_power_w,
                        peak_power_w
                    FROM recordings WHERE device_id = ? AND ends_at IS NOT NULL
                        AND missing_seconds=0 AND sample_count>=2
                    ORDER BY ends_at DESC LIMIT 30
                    """,
                    (device.device_id,),
                ).fetchall()
                completed = len(sessions)
                confidence = min(0.95, 0.25 + completed * 0.10) if completed else 0.0
                cards.append(
                    {
                        "card_id": f"energy-device-card:{device.device_id}",
                        "device_id": device.device_id,
                        "name": device.name,
                        "power_entity_id": device.power_entity_id,
                        "energy_entity_id": device.energy_entity_id,
                        "availability": (
                            str(status["availability"]) if status is not None else "unknown"
                        ),
                        "active": (
                            status is not None and status["power_w"] is not None
                            and float(status["power_w"]) >= device.active_threshold_w
                        ),
                        "recording": dict(active) if active is not None else None,
                        "legacy_session_count": connection.execute(
                            "SELECT COUNT(*) FROM sessions WHERE device_id=?", (device.device_id,)
                        ).fetchone()[0],
                        "current_power_w": (
                            float(status["power_w"])
                            if status is not None and status["power_w"] is not None
                            else None
                        ),
                        "last_observed_at": (
                            str(status["observed_at"]) if status is not None else None
                        ),
                        "expected_power_w": (
                            sum(float(row["average_power_w"]) for row in sessions) / completed
                            if completed
                            else None
                        ),
                        "expected_duration_seconds": (
                            median(float(row["duration_seconds"]) for row in sessions)
                            if completed
                            else None
                        ),
                        "expected_energy_wh": (
                            median(float(row["energy_wh"]) for row in sessions)
                            if completed
                            else None
                        ),
                        "peak_power_w": (
                            max(float(row["peak_power_w"]) for row in sessions)
                            if completed
                            else None
                        ),
                        "confidence": confidence,
                        "completed_session_count": completed,
                        "profile_status": "ready" if completed >= 2 else "learning",
                        "profile_revision": completed,
                        "method_version": PROFILE_METHOD_VERSION,
                    }
                )
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "producer": "picot-energy-devices",
            "revision": int(revision_row["value"]) if revision_row is not None else 1,
            "generated_at": self._now().isoformat(),
            "observer_only": True,
            "planning_authority": False,
            "cards": cards,
        }

    def database_size_bytes(self) -> int:
        return self._path.stat().st_size if self._path.exists() else 0
