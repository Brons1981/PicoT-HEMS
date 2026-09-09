"""Explicit, durable learning recordings; no automatic session boundaries."""

from __future__ import annotations

import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    recording_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    name TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    duration_seconds REAL,
    observed_energy_wh REAL,
    missing_seconds REAL,
    peak_power_w REAL,
    sample_count INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_recording
    ON recordings(device_id) WHERE ends_at IS NULL;
CREATE TABLE IF NOT EXISTS recording_samples (
    recording_id INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    power_w REAL,
    energy_meter_wh REAL,
    error TEXT,
    PRIMARY KEY(recording_id, observed_at)
);
"""


def append_sample(
    connection: sqlite3.Connection, device_id: str, timestamp: datetime,
    power_w: float | None, energy_meter_wh: float | None = None,
    error: str | None = None,
) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO recording_samples
        SELECT recording_id, ?, ?, ?, ? FROM recordings
        WHERE device_id=? AND ends_at IS NULL AND starts_at<=?
        AND NOT EXISTS (SELECT 1 FROM recording_samples s
            WHERE s.recording_id=recordings.recording_id AND s.observed_at>=?)""",
        (timestamp.isoformat(), power_w, energy_meter_wh, error,
         device_id, timestamp.isoformat(), timestamp.isoformat()),
    )


def finish(
    connection: sqlite3.Connection, device_id: str, timestamp: datetime,
    maximum_gap: float,
) -> None:
    recording = connection.execute(
        "SELECT * FROM recordings WHERE device_id=? AND ends_at IS NULL", (device_id,)
    ).fetchone()
    if recording is None:
        raise ValueError("Er loopt geen opname voor dit apparaat")
    start = datetime.fromisoformat(recording["starts_at"])
    if timestamp <= start:
        raise ValueError("Het einde moet na de start liggen")
    rows = connection.execute(
        "SELECT * FROM recording_samples WHERE recording_id=? ORDER BY observed_at",
        (recording["recording_id"],),
    ).fetchall()
    if rows and datetime.fromisoformat(rows[-1]["observed_at"]) > timestamp:
        raise ValueError("Het einde ligt vóór de laatste meting")
    energy = 0.0
    missing = 0.0
    peak = 0.0
    for index, row in enumerate(rows):
        left = datetime.fromisoformat(row["observed_at"])
        right = (datetime.fromisoformat(rows[index + 1]["observed_at"])
                 if index + 1 < len(rows) else timestamp)
        elapsed = (right - left).total_seconds()
        if row["power_w"] is None or elapsed > maximum_gap:
            missing += elapsed
        else:
            energy += float(row["power_w"]) * elapsed / 3600
        if row["power_w"] is not None:
            peak = max(peak, float(row["power_w"]))
    duration = (timestamp - start).total_seconds()
    if not rows:
        missing = duration
    else:
        missing += (datetime.fromisoformat(rows[0]["observed_at"]) - start).total_seconds()
    connection.execute(
        """UPDATE recordings SET ends_at=?, duration_seconds=?, observed_energy_wh=?,
        missing_seconds=?, peak_power_w=?, sample_count=? WHERE recording_id=?""",
        (timestamp.isoformat(), duration, energy, missing, peak,
         sum(row["power_w"] is not None for row in rows), recording["recording_id"]),
    )
