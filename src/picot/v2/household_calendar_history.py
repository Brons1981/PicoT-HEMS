"""Passive, resumable calendar index of accepted household observations.

No planner consumes this database or its reports. The source remains authoritative.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from picot.v2.household_load_history import _decode_observation
from picot.v2.passive_history.calendar import AMSTERDAM, microseconds

CALENDAR_DATABASE_PATH = Path("/data/picot_v2_household_calendar.sqlite")
CALENDAR_REPORT_PATH = Path("/data/picot_v2_household_calendar.json")
BATCH_LINES = 512
MAX_LINE_BYTES = 64 * 1024
MAX_GAP_US = 180_000_000
QUARTER_US = 900_000_000
DATABASE_BYTES = 128 * 1024**2
FREE_RESERVE_BYTES = 128 * 1024**2
METHOD_VERSION = "accepted-household-linear-gap180-calendar:v1"


def calendar_dashboard_view(path: Path | None) -> dict[str, Any]:
    """Read one atomically published bounded report, never the writer's database."""
    if path is None or not path.is_file() or path.is_symlink():
        return {"status": "collecting", "observer_only": True}
    try:
        with path.open("rb") as handle:
            raw = handle.read(8 * 1024**2 + 1)
        if len(raw) > 8 * 1024**2:
            raise ValueError("calendar report byte budget exceeded")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("invalid calendar report schema")
        data["days"] = [{k: v for k, v in day.items()
                         if k not in {"quarters", "retrospective_comparison"}}
                        for day in data["days"]]
        return {"status": "ready", **data}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"status": "unavailable", "observer_only": True}


class HouseholdCalendarHistory:
    """A single isolated writer; data and source cursor commit together."""

    def __init__(self, path: Path) -> None:
        if path.is_symlink():
            raise ValueError("calendar database must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA cache_size=-2048")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError("unsupported household calendar schema")
        if version == 0:
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE quarter(
                    start_us INTEGER PRIMARY KEY, local_date TEXT NOT NULL,
                    weekday INTEGER NOT NULL, iso_year INTEGER NOT NULL,
                    iso_week INTEGER NOT NULL, clock_quarter INTEGER NOT NULL,
                    fold INTEGER NOT NULL, sample_count INTEGER NOT NULL DEFAULT 0,
                    sample_sum_w REAL NOT NULL DEFAULT 0,
                    first_sample_us INTEGER, last_sample_us INTEGER,
                    energy_wh REAL NOT NULL DEFAULT 0, covered_us INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX quarter_day ON quarter(local_date,start_us);
                CREATE TABLE checkpoint(
                    id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL,
                    identity TEXT NOT NULL, offset_bytes INTEGER NOT NULL,
                    last_us INTEGER, last_power_w REAL, previous_valid INTEGER NOT NULL,
                    accepted INTEGER NOT NULL, rejected INTEGER NOT NULL,
                    skipped_old INTEGER NOT NULL
                );
                PRAGMA user_version=1;
                COMMIT;
            """)
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        self.db.execute(f"PRAGMA max_page_count={DATABASE_BYTES // page_size}")

    def close(self) -> None:
        self.db.close()

    def _quarter(self, start_us: int) -> None:
        local = datetime.fromtimestamp(start_us / 1_000_000, UTC).astimezone(AMSTERDAM)
        iso = local.isocalendar()
        self.db.execute(
            "INSERT OR IGNORE INTO quarter(start_us,local_date,weekday,iso_year,"
            "iso_week,clock_quarter,fold) VALUES(?,?,?,?,?,?,?)",
            (start_us, local.date().isoformat(), local.weekday() + 1,
             iso.year, iso.week, local.hour * 4 + local.minute // 15, local.fold),
        )

    def _integrate(self, a: int, pa: float, b: int, pb: float) -> None:
        if b - a > MAX_GAP_US:
            return
        cursor = a
        while cursor < b:
            quarter = cursor // QUARTER_US * QUARTER_US
            end = min(b, quarter + QUARTER_US)
            left = pa + (pb - pa) * (cursor - a) / (b - a)
            right = pa + (pb - pa) * (end - a) / (b - a)
            self._quarter(quarter)
            self.db.execute(
                "UPDATE quarter SET energy_wh=energy_wh+?,covered_us=covered_us+? "
                "WHERE start_us=?",
                ((left + right) / 2 * (end - cursor) / 3_600_000_000,
                 end - cursor, quarter),
            )
            cursor = end

    def ingest_batch(
        self, source: Path, *, limit: int = BATCH_LINES,
        free_reserve: int = FREE_RESERVE_BYTES,
    ) -> dict[str, Any]:
        """Consume complete lines only; interrupted writes remain retryable."""
        if not 1 <= limit <= BATCH_LINES:
            raise ValueError("calendar batch limit must be 1..512")
        if source.is_symlink():
            raise ValueError("calendar source must not be a symlink")
        if not source.exists():
            return {"state": "source_missing", "caught_up": False}
        if shutil.disk_usage(source.parent).free < free_reserve:
            return {"state": "paused_storage", "caught_up": False}
        with source.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            identity = f"{stat.st_dev}:{stat.st_ino}"
            previous = self.db.execute("SELECT * FROM checkpoint WHERE id=1").fetchone()
            state: dict[str, Any] = dict(previous) if previous else {
                "source": str(source.resolve()), "identity": identity, "offset_bytes": 0,
                "last_us": None, "last_power_w": None, "previous_valid": 0,
                "accepted": 0, "rejected": 0, "skipped_old": 0,
            }
            state.pop("id", None)
            if (state["identity"] != identity or state["offset_bytes"] > stat.st_size
                    or state["source"] != str(source.resolve())):
                state.update(source=str(source.resolve()), identity=identity, offset_bytes=0)
                # Keep the watermark across rotation; old records never add energy twice.
                state["previous_valid"] = 0
            handle.seek(state["offset_bytes"])
            consumed = 0
            with self.db:
                for _ in range(limit):
                    offset = handle.tell()
                    line = handle.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_LINE_BYTES:
                        raise ValueError("household history line exceeds 64 KiB")
                    if not line.endswith(b"\n"):
                        handle.seek(offset)
                        break
                    consumed += 1
                    state["offset_bytes"] = handle.tell()
                    try:
                        observation = _decode_observation(line.decode("utf-8"))
                    except UnicodeDecodeError:
                        observation = None
                    if observation is None:
                        state["rejected"] += 1
                        state["previous_valid"] = 0
                        continue
                    stamp = microseconds(observation.sampled_at)
                    if state["last_us"] is not None and stamp <= state["last_us"]:
                        state["skipped_old"] += 1
                        continue
                    power = observation.power_w
                    if state["previous_valid"]:
                        self._integrate(state["last_us"], state["last_power_w"], stamp, power)
                    quarter = stamp // QUARTER_US * QUARTER_US
                    self._quarter(quarter)
                    self.db.execute(
                        "UPDATE quarter SET sample_count=sample_count+1,"
                        "sample_sum_w=sample_sum_w+?,"
                        "first_sample_us=COALESCE(first_sample_us,?),last_sample_us=? "
                        "WHERE start_us=?", (power, stamp, stamp, quarter),
                    )
                    state.update(last_us=stamp, last_power_w=power, previous_valid=1)
                    state["accepted"] += 1
                columns = ",".join(state)
                placeholders = ",".join("?" for _ in state)
                self.db.execute(
                    f"INSERT OR REPLACE INTO checkpoint(id,{columns}) VALUES(1,{placeholders})",
                    tuple(state.values()),
                )
            return {"state": "ready", "consumed_lines": consumed,
                    "caught_up": state["offset_bytes"] == os.fstat(handle.fileno()).st_size,
                    **state}

    def report(self, *, now: datetime) -> dict[str, Any]:
        from picot.v2.household_calendar_report import build_calendar_report

        return build_calendar_report(self.db, now=now)

    def publish(self, path: Path, *, now: datetime) -> None:
        """A download sees one complete report, including explicit backfill progress."""
        if path.is_symlink():
            raise ValueError("calendar report must not be a symlink")
        data = self.report(now=now)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".pending",
                                            dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, allow_nan=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
