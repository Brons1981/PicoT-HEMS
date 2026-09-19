"""Explicit offline retention preview and immutable comparison projection.

Never deletes from the source, publishes into live storage, or removes evidence.
A projection references the original evidence directory; it is not a replay backup.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .calendar import AMSTERDAM, microseconds, retention_tier
from .storage import SCHEMA_VERSION, encode

PROJECTION_ID = 0x50485450
POLICY = "passive-comparison-projection:v1"
FLOW_NAMES = {"grid_import", "grid_export", "pv_generation", "battery_charge", "battery_discharge"}
LIMIT = 256 * 1024**2


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def snapshot(root: Path) -> Iterator[sqlite3.Connection]:
    root = root.absolute()
    for name in (
        "passive-history.owner",
        "history.sqlite",
        "history.sqlite-wal",
        "history.sqlite-shm",
    ):
        if (root / name).is_symlink():
            raise ValueError("history storage must not follow symlinks")
    if (root / "passive-history.owner").read_text() != "picot-passive-history-v1\n":
        raise ValueError("not owned passive history")
    db = sqlite3.connect((root / "history.sqlite").as_uri() + "?mode=ro", uri=True, timeout=0)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 120
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if db.execute("PRAGMA application_id").fetchone()[0] != 0:
            raise ValueError("source must be an original history database")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("unsupported history schema")
        size = (
            db.execute("PRAGMA page_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        )
        if size > LIMIT:
            raise ValueError("offline history size limit")
        yield db
    finally:
        db.close()


def tables(db: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]


def fingerprint(db: sqlite3.Connection) -> str:
    """Hash the same consistent logical snapshot used for preview and copying."""
    digest = sha256()
    for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"):
        digest.update((encode(tuple(row)) + "\n").encode())
    for table in tables(db):
        digest.update((encode(table) + "\n").encode())
        columns = len(db.execute(f"PRAGMA table_info({quoted(table)})").fetchall())
        order = ",".join(str(i) for i in range(1, columns + 1))
        for row in db.execute(f"SELECT * FROM {quoted(table)} ORDER BY {order}"):
            digest.update((encode(tuple(row)) + "\n").encode())
    return digest.hexdigest()


def eligible(db: sqlite3.Connection, group: sqlite3.Row) -> str:
    key = (group["scope_id"], group["metric_id"], group["day_id"])
    if group["n"] > 101:
        return "revisions_or_interval_limit_require_review"
    intervals = db.execute(
        "SELECT * FROM interval_value WHERE scope_id=? AND metric_id=? AND day_id=? "
        "ORDER BY start_us",
        key,
    ).fetchall()
    days = db.execute(
        "SELECT * FROM day_value WHERE scope_id=? AND metric_id=? AND day_id=?", key
    ).fetchall()
    if any(r["revision"] != 1 for r in intervals) or len(days) > 1:
        return "revisions_require_review"
    if not days:
        return "missing_day_aggregate"
    day = days[0]
    if day["revision"] != 1 or any(r["provenance_id"] != day["provenance_id"] for r in intervals):
        return "mixed_provenance_requires_review"
    closed = db.execute(
        "SELECT 1 FROM day_close WHERE scope_id=? AND day_id=? "
        "AND state IN ('CLOSED_COMPLETE','CLOSED_PARTIAL') AND checked_until_us>=?",
        (group["scope_id"], group["day_id"], group["end_us"]),
    ).fetchone()
    if not closed:
        return "day_not_closed"
    if any(
        not (group["start_us"] <= r["start_us"] < r["end_us"] <= group["end_us"]) for r in intervals
    ):
        return "invalid_interval_boundaries"
    if any(a["end_us"] > b["start_us"] for a, b in zip(intervals, intervals[1:], strict=False)):
        return "overlapping_intervals"
    good = [
        r
        for r in intervals
        if r["value"] is not None
        and r["end_us"] - r["start_us"] == 900_000_000
        and r["start_us"] % 900_000_000 == 0
    ]
    if any(not math.isfinite(r["value"]) for r in good):
        return "nonfinite_value"
    partial = sum(r["value"] for r in good) if good else None
    expected = group["quarter_count"]
    full = partial if len(good) == expected else None
    # Exact equality: ambiguity retains the original detail; no new tolerance.
    if (day["partial_value"], day["value"], day["usable_intervals"], day["expected_intervals"]) != (
        partial,
        full,
        len(good),
        expected,
    ):
        return "aggregate_mismatch"
    quality = db.execute("SELECT * FROM quality WHERE id=?", (day["quality_id"],)).fetchone()
    reason = db.execute(
        "SELECT payload_json FROM definition WHERE id=?", (quality["reason_def"],)
    ).fetchone()
    if (
        quality["evidence_kind"] != "derived"
        or quality["validity"] != "unvalidated_flow"
        or quality["coverage"] != ("full" if len(good) == expected else "partial")
        or reason is None
        or json.loads(reason[0]) != "sum_available_archived_closed_flow_values:v1"
    ):
        return "unknown_aggregate_method"
    return "proven_day_aggregate"


def report_for(db: sqlite3.Connection, today: date) -> dict[str, Any]:
    source_hash = fingerprint(db)
    groups: list[dict[str, Any]] = []
    query = """SELECT i.scope_id,i.metric_id,i.day_id,count(*) AS n,d.local_date,
        d.start_us,d.end_us,d.quarter_count,m.payload_json FROM interval_value i
        JOIN local_day d ON d.id=i.day_id JOIN definition m ON m.id=i.metric_id
        GROUP BY i.scope_id,i.metric_id,i.day_id
        ORDER BY i.scope_id,i.metric_id,i.day_id LIMIT 20001"""
    for row in db.execute(query):
        if len(groups) == 20000:
            raise ValueError("offline group limit")
        metric = json.loads(row["payload_json"])
        tier = retention_tier(date.fromisoformat(row["local_date"]), today)
        reason = tier
        if isinstance(metric, dict) and metric.get("name") == "household":
            reason = "household_retained"
        elif (
            not isinstance(metric, dict)
            or metric.get("name") not in FLOW_NAMES
            or metric.get("unit") != "Wh"
        ):
            reason = "unknown_metric_retained"
        elif tier == "long_term":
            reason = eligible(db, row)
        groups.append(
            {
                "scope_id": row["scope_id"],
                "metric_id": row["metric_id"],
                "day_id": row["day_id"],
                "local_date": row["local_date"],
                "metric": metric,
                "intervals": row["n"],
                "tier": tier,
                "reason": reason,
                "omit_values": reason == "proven_day_aggregate",
            }
        )
    report: dict[str, Any] = {
        "policy": POLICY,
        "today_amsterdam": today.isoformat(),
        "source_fingerprint": source_hash,
        "groups": groups,
        "omit_intervals": sum(g["intervals"] for g in groups if g["omit_values"]),
        "evidence_files_removed": 0,
        "purpose": "comparison_projection_not_replay_backup",
    }
    report["token"] = sha256(encode(report).encode()).hexdigest()
    return report


def preview(root: Path, today: date) -> dict[str, Any]:
    with snapshot(root) as db:
        return report_for(db, today)


def write_projection(
    source: sqlite3.Connection, target: sqlite3.Connection, report: dict[str, Any], root: Path
) -> None:
    schema = source.execute(
        "SELECT type,sql FROM sqlite_master WHERE sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,name"
    ).fetchall()
    target.execute("PRAGMA foreign_keys=ON")
    target.execute("PRAGMA synchronous=FULL")
    target.execute(
        f"PRAGMA max_page_count={LIMIT // target.execute('PRAGMA page_size').fetchone()[0]}"
    )
    with target:
        target.execute("BEGIN")
        target.execute("PRAGMA defer_foreign_keys=ON")
        for item in schema:
            if item["type"] != "trigger":
                target.execute(item["sql"])
        target.execute("""CREATE TABLE compacted_interval_quality(
            scope_id INTEGER NOT NULL REFERENCES definition(id),
            metric_id INTEGER NOT NULL REFERENCES definition(id),
            start_us INTEGER NOT NULL,end_us INTEGER NOT NULL,revision INTEGER NOT NULL,
            day_id INTEGER NOT NULL REFERENCES local_day(id),
            quality_id INTEGER NOT NULL REFERENCES quality(id),
            provenance_id INTEGER NOT NULL REFERENCES provenance(id),
            recorded_us INTEGER NOT NULL,previous_revision INTEGER,
            PRIMARY KEY(scope_id,metric_id,start_us,end_us,revision)) WITHOUT ROWID""")
        omitted = {
            (g["scope_id"], g["metric_id"], g["day_id"])
            for g in report["groups"]
            if g["omit_values"]
        }
        for table in tables(source):
            for row in source.execute(f"SELECT * FROM {quoted(table)}"):
                values = tuple(row)
                destination = table
                if (
                    table == "interval_value"
                    and (row["scope_id"], row["metric_id"], row["day_id"]) in omitted
                ):
                    destination = "compacted_interval_quality"
                    values = tuple(row[k] for k in row.keys() if k != "value")
                target.execute(
                    f"INSERT INTO {quoted(destination)} VALUES({','.join('?' for _ in values)})",
                    values,
                )
        target.execute(
            "INSERT INTO history_meta VALUES(?,?)", ("projection_source_root", str(root.resolve()))
        )
        target.execute(
            "INSERT INTO history_meta VALUES(?,?)",
            ("projection_role", "comparison_only_external_evidence"),
        )
        policy_id = target.execute("SELECT coalesce(max(id),0)+1 FROM definition").fetchone()[0]
        target.execute(
            "INSERT INTO definition VALUES(?,?,?,?,?)",
            (policy_id, "retention_policy", POLICY, "v1", encode({"policy": POLICY})),
        )
        target.execute(
            "INSERT INTO retention_batch VALUES(?,?,?,?,?)",
            (
                report["token"],
                microseconds(datetime.now(UTC)),
                policy_id,
                encode(report),
                "comparison_copy_complete",
            ),
        )
        for item in schema:
            if item["type"] == "trigger":
                target.execute(item["sql"])
        for action in ("UPDATE", "DELETE"):
            target.execute(
                f"CREATE TRIGGER immutable_compacted_{action} BEFORE {action} "
                "ON compacted_interval_quality "
                "BEGIN SELECT RAISE(ABORT,'immutable history revision'); END"
            )
        target.execute(f"PRAGMA application_id={PROJECTION_ID}")
        target.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("projection foreign key failure")
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("projection integrity failure")


def compact_copy(
    root: Path, output: Path, today: date, expected_token: str, *, free_reserve: int = 128 * 1024**2
) -> dict[str, Any]:
    """Publish a new comparison file only after a fresh preview matches and checks pass."""
    output = output.parent.resolve() / output.name
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if output.is_relative_to(root.resolve()):
        raise ValueError("projection must be outside source history")
    with snapshot(root) as source:
        report = report_for(source, today)
        if report["token"] != expected_token:
            raise ValueError("stale retention preview")
        source_size = (
            source.execute("PRAGMA page_count").fetchone()[0]
            * source.execute("PRAGMA page_size").fetchone()[0]
        )
        if shutil.disk_usage(output.parent).free < source_size * 2 + free_reserve:
            raise OSError("insufficient projection space")
        fd, name = tempfile.mkstemp(
            prefix=".history-projection-", suffix=".sqlite", dir=output.parent
        )
        os.close(fd)
        pending = Path(name)
        try:
            target = sqlite3.connect(pending)
            deadline = time.monotonic() + 120
            target.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            try:
                write_projection(source, target, report, root)
            finally:
                target.close()
            with pending.open("rb") as handle:
                os.fsync(handle.fileno())
            os.link(pending, output)  # Atomic, never replace an existing file.
            directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            pending.unlink(missing_ok=True)
            Path(name + "-journal").unlink(missing_ok=True)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(AMSTERDAM).date())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-token")
    args = parser.parse_args()
    if args.output:
        if not args.expected_token:
            parser.error("--output requires --expected-token from a fresh preview")
        result = compact_copy(args.root, args.output, args.today, args.expected_token)
    else:
        result = preview(args.root, args.today)
    print(encode(result))


if __name__ == "__main__":
    main()
