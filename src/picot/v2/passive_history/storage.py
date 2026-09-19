"""Own-directory SQLite storage; versioned compact facts, never planner authority."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from .calendar import AMSTERDAM, bounds, microseconds

SCHEMA_VERSION = 1


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decimal_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        result = str(value)
        if not Decimal(result).is_finite():
            raise ValueError("nonfinite historical amount")
        return result
    except InvalidOperation as exc:
        raise ValueError("invalid historical decimal") from exc


def own_directory(root: Path) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "passive-history.owner"
    if marker.is_symlink():
        raise ValueError("history owner marker must not be a symlink")
    if not marker.exists():
        if any(root.iterdir()):
            raise ValueError("refusing nonempty directory not owned by passive history")
        with marker.open("x") as handle:
            handle.write("picot-passive-history-v1\n")
    if marker.read_text() != "picot-passive-history-v1\n":
        raise ValueError("unknown passive history directory owner")
    for name in ("objects", "history.sqlite", "history.sqlite-wal", "history.sqlite-shm"):
        if (root / name).is_symlink():
            raise ValueError("history storage must not follow symlinks")
    return root


class HistoryStore:
    """One writer. Callers group related changes with `with store.db:`."""

    def __init__(self, root: Path, *, database_limit: int = 256 * 1024**2) -> None:
        self.root = own_directory(root)
        self.db = sqlite3.connect(self.root / "history.sqlite", timeout=0)
        if self.db.execute("PRAGMA application_id").fetchone()[0] != 0:
            self.db.close()
            raise ValueError("comparison projection cannot be opened as writable history")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            self.db.close()
            raise ValueError("unsupported history schema")
        if version == 0:
            schema = Path(__file__).with_name("schema.sql").read_text()
            schema += """
                CREATE TABLE history_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE job(digest TEXT PRIMARY KEY,path TEXT NOT NULL,
                    state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,reason TEXT);
                CREATE INDEX job_state ON job(state,digest);
                CREATE TABLE poll_identity(digest TEXT NOT NULL REFERENCES evidence_object(digest),
                    plan_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,evaluation_id TEXT NOT NULL,
                    PRIMARY KEY(digest,plan_id)) WITHOUT ROWID;
                CREATE TABLE revision_source(table_name TEXT NOT NULL,key_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    provenance_id INTEGER NOT NULL REFERENCES provenance(id),
                    PRIMARY KEY(table_name,key_json,revision,provenance_id)) WITHOUT ROWID;
                CREATE TABLE plan_link(plan_id TEXT NOT NULL REFERENCES plan_evidence(plan_id),
                    digest TEXT NOT NULL REFERENCES evidence_object(digest),
                    PRIMARY KEY(plan_id,digest)) WITHOUT ROWID;
                CREATE TABLE evidence_observation(id INTEGER PRIMARY KEY,digest TEXT NOT NULL,
                    status TEXT NOT NULL,reason TEXT NOT NULL,observed_us INTEGER NOT NULL);
                CREATE VIEW usable_plan_objects AS SELECT l.plan_id,l.digest FROM plan_link l
                    JOIN evidence_object e ON e.digest=l.digest WHERE e.status='verified_record';
            """
            for table in (
                "interval_value",
                "tariff",
                "day_value",
                "day_close",
                "financial_result",
                "evidence_observation",
            ):
                for action in ("UPDATE", "DELETE"):
                    schema += (
                        f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable history revision'); END;"
                    )
            try:
                self.db.executescript(
                    "BEGIN IMMEDIATE;" + schema + f"PRAGMA user_version={SCHEMA_VERSION};COMMIT;"
                )
            except Exception:
                self.db.rollback()
                self.db.close()
                raise
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        pages = database_limit // page_size
        if self.db.execute("PRAGMA page_count").fetchone()[0] > pages:
            self.db.close()
            raise ValueError("history database already exceeds budget")
        self.db.execute(f"PRAGMA max_page_count={pages}")

    def close(self) -> None:
        self.db.close()

    def definition(self, kind: str, value: object) -> int:
        body = encode(value)
        digest = sha256(body.encode()).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO definition(kind,external_id,version,payload_json) "
            "VALUES(?,?,'v1',?)",
            (kind, digest, body),
        )
        return int(
            self.db.execute(
                "SELECT id FROM definition WHERE kind=? AND external_id=? AND version='v1'",
                (kind, digest),
            ).fetchone()[0]
        )

    def day(self, day: date) -> int:
        start, end = bounds(day)
        iso = day.isocalendar()
        rule = self.definition("calendar", {"zone": "Europe/Amsterdam", "version": 1})
        self.db.execute(
            "INSERT OR IGNORE INTO local_day(local_date,start_us,end_us,weekday,"
            "year,month,iso_year,iso_week,weekday_ordinal,quarter_count,calendar_def) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                day.isoformat(),
                start,
                end,
                day.weekday() + 1,
                day.year,
                day.month,
                iso.year,
                iso.week,
                (day.day - 1) // 7 + 1,
                (end - start) // 900_000_000,
                rule,
            ),
        )
        return int(
            self.db.execute(
                "SELECT id FROM local_day WHERE local_date=?", (day.isoformat(),)
            ).fetchone()[0]
        )

    def provenance(self, digest: str, method: str, captured: int) -> int:
        source = self.definition("source", {"digest": digest})
        method_id = self.definition("method", method)
        row = self.db.execute(
            "SELECT id FROM provenance WHERE source_def=? AND method_def=? AND captured_us=?",
            (source, method_id, captured),
        ).fetchone()
        if row:
            return int(row[0])
        cursor = self.db.execute(
            "INSERT INTO provenance(source_def,method_def,evidence_digest,"
            "evidence_status,captured_us) VALUES(?,?,?,'available',?)",
            (source, method_id, digest, captured),
        )
        return int(cursor.lastrowid or 0)

    def quality(self, evidence: str, coverage: str, validity: str, reason: object) -> int:
        reason_id = self.definition("quality_reason", reason)
        method = self.definition("method", "preserve_archived_quality:v1")
        row = self.db.execute(
            "SELECT id FROM quality WHERE evidence_kind=? AND coverage=? "
            "AND validity=? AND reason_def=? AND method_def=?",
            (evidence, coverage, validity, reason_id, method),
        ).fetchone()
        if row:
            return int(row[0])
        result = self.db.execute(
            "INSERT INTO quality(evidence_kind,coverage,validity,reason_def,"
            "method_def) VALUES(?,?,?,?,?)",
            (evidence, coverage, validity, reason_id, method),
        )
        return int(result.lastrowid or 0)

    def append(self, table: str, key: dict[str, object], values: dict[str, object]) -> int:
        """Append changed semantic content; A→B→A remains three revisions."""
        allowed = {"interval_value", "tariff", "day_value", "day_close", "financial_result"}
        if table not in allowed:
            raise ValueError("not a revision table")
        columns = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
        if not (key.keys() | values.keys()) <= columns:
            raise ValueError("invalid revision columns")
        where = " AND ".join(f"{k}=?" for k in key)
        if "provenance_id" in values:
            prior = self.db.execute(
                "SELECT revision FROM revision_source WHERE table_name=? AND key_json=? "
                "AND provenance_id=?",
                (table, encode(key), values["provenance_id"]),
            ).fetchone()
            if prior:
                return int(prior[0])
        if table == "day_close":
            prior = self.db.execute(
                f"SELECT revision FROM day_close WHERE {where} AND manifest_def=?",
                (*key.values(), values["manifest_def"]),
            ).fetchone()
            if prior:
                return int(prior[0])
        old = self.db.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY revision DESC LIMIT 1",
            tuple(key.values()),
        ).fetchone()
        encode(values)  # SQLite must not turn nonfinite float values silently into NULL.
        if old and all(old[k] == v for k, v in values.items() if k != "provenance_id"):
            if "provenance_id" in values:
                self.db.execute(
                    "INSERT OR IGNORE INTO revision_source VALUES(?,?,?,?)",
                    (table, encode(key), old["revision"], values["provenance_id"]),
                )
            return int(old["revision"])
        revision = old["revision"] + 1 if old else 1
        row = (
            key
            | values
            | {
                "revision": revision,
                "recorded_us": microseconds(datetime.now(UTC)),
                "previous_revision": old["revision"] if old else None,
            }
        )
        self.db.execute(
            f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' for _ in row)})",
            tuple(row.values()),
        )
        if "provenance_id" in values:
            self.db.execute(
                "INSERT OR IGNORE INTO revision_source VALUES(?,?,?,?)",
                (table, encode(key), revision, values["provenance_id"]),
            )
        return int(revision)

    def observe(self, digest: str, status: str, reason: str) -> None:
        old = self.db.execute(
            "SELECT status,reason FROM evidence_observation WHERE digest=? "
            "ORDER BY id DESC LIMIT 1",
            (digest,),
        ).fetchone()
        if old and tuple(old) == (status, reason):
            return
        self.db.execute(
            "INSERT INTO evidence_observation(digest,status,reason,observed_us) VALUES(?,?,?,?)",
            (digest, status, reason, microseconds(datetime.now(UTC))),
        )

    def import_record(self, value: dict[str, Any], digest: str) -> None:
        """Preserve source semantics; no simulation, financial recomputation or HA reads."""
        if "poll" in value:
            self._link_poll(value["poll"], digest)
        elif "execution_plans" in value:
            for plan in value["execution_plans"].values():
                self._register_plan(plan)
        elif "aligned_measurements" in value:
            self._measurements(value, digest)
        elif "days" in value:
            self._days_and_prices(value, digest)
        # Other source shapes remain byte-preserved, without invented derived records.

    def _register_plan(self, plan: dict[str, Any]) -> None:
        args = (
            plan["plan_id"],
            plan["snapshot_id"],
            plan["evaluation_id"],
            microseconds(plan["valid_from"]),
            microseconds(plan["valid_until"]),
        )
        old = self.db.execute(
            "SELECT plan_id,snapshot_id,evaluation_id,valid_from_us,valid_until_us "
            "FROM plan_evidence WHERE plan_id=?",
            (args[0],),
        ).fetchone()
        if old and tuple(old) != args:
            raise ValueError("conflicting registered plan identity")
        self.db.execute(
            "INSERT OR IGNORE INTO plan_evidence(plan_id,snapshot_id,evaluation_id,"
            "valid_from_us,valid_until_us,availability) VALUES(?,?,?,?,?,?)",
            (*args, "registered_identity_not_admission_certified"),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO plan_link SELECT plan_id,digest FROM poll_identity "
            "WHERE plan_id=? AND snapshot_id=? AND evaluation_id=?",
            args[:3],
        )

    def _link_poll(self, poll: dict[str, Any], digest: str) -> None:
        source = poll.get("planning_input") or {}
        evaluation = poll.get("evaluation") or {}
        plans = (poll.get("execution_plan_set") or {}).get("plans", [])
        if len(plans) > 256:
            raise ValueError("plan link limit")
        for plan in plans:
            if not all(
                isinstance(v, str) and v
                for v in (
                    plan.get("plan_id"),
                    source.get("snapshot_id"),
                    evaluation.get("evaluation_id"),
                )
            ):
                continue
            self.db.execute(
                "INSERT OR IGNORE INTO poll_identity VALUES(?,?,?,?)",
                (digest, plan["plan_id"], source["snapshot_id"], evaluation["evaluation_id"]),
            )
            row = self.db.execute(
                "SELECT 1 FROM plan_evidence WHERE plan_id=? AND snapshot_id=? AND evaluation_id=?",
                (plan.get("plan_id"), source.get("snapshot_id"), evaluation.get("evaluation_id")),
            ).fetchone()
            if row:
                self.db.execute(
                    "INSERT OR IGNORE INTO plan_link VALUES(?,?)", (plan["plan_id"], digest)
                )

    def _measurements(self, data: dict[str, Any], digest: str) -> None:
        day = datetime.fromisoformat(data["starts_at"]).astimezone(AMSTERDAM).date()
        day_id = self.day(day)
        start, end = bounds(day)
        scope = self.definition("scope", "home-battery")
        rows = data["aligned_measurements"]["intervals"]
        if len(rows) > 101:
            raise ValueError("day interval limit")
        prov = self.provenance(digest, "archived-quarter-values:v1", microseconds(data["ends_at"]))
        seen: set[tuple[int, int]] = set()
        for row in rows:
            a, b = microseconds(row["starts_at"]), microseconds(row["ends_at"])
            if not start <= a < b <= end or (a, b) in seen:
                raise ValueError("invalid or duplicate interval in local day")
            seen.add((a, b))
            for metric, number in {
                **row["energy_wh"],
                "household": row["household_energy_wh"],
            }.items():
                quality = self.quality(
                    "derived",
                    "available" if number is not None else "missing",
                    row["status"] if metric == "household" else "unvalidated_flow",
                    row.get("reason"),
                )
                self.append(
                    "interval_value",
                    {
                        "scope_id": scope,
                        "metric_id": self.definition("metric", {"name": metric, "unit": "Wh"}),
                        "start_us": a,
                        "end_us": b,
                    },
                    {
                        "day_id": day_id,
                        "value": number,
                        "quality_id": quality,
                        "provenance_id": prov,
                    },
                )
        good = [
            r
            for r in rows
            if r["status"] == "derived"
            and r["household_energy_wh"] is not None
            and microseconds(r["ends_at"]) - microseconds(r["starts_at"]) == 900_000_000
            and microseconds(r["starts_at"]) % 900_000_000 == 0
        ]
        expected = (end - start) // 900_000_000
        complete = len({microseconds(r["starts_at"]) for r in good}) == expected
        elapsed = microseconds(data["ends_at"]) >= end
        partial = sum(r["household_energy_wh"] for r in good) if good else None
        quality = self.quality(
            "derived",
            "full" if complete else "partial",
            "archived_household_sum",
            "no_missing_values_filled",
        )
        self.append(
            "day_value",
            {
                "scope_id": scope,
                "day_id": day_id,
                "metric_id": self.definition("metric", {"name": "household", "unit": "Wh"}),
            },
            {
                "value": partial if complete and elapsed else None,
                "partial_value": partial,
                "expected_intervals": expected,
                "usable_intervals": len(good),
                "quality_id": quality,
                "provenance_id": prov,
            },
        )
        # Keep other day flows independently, without promoting their physical quality.
        for metric in sorted({name for row in rows for name in row["energy_wh"]}):
            closed = [
                row
                for row in rows
                if microseconds(row["ends_at"]) - microseconds(row["starts_at"]) == 900_000_000
                and microseconds(row["starts_at"]) % 900_000_000 == 0
                and row["energy_wh"].get(metric) is not None
            ]
            known_sum = sum(row["energy_wh"][metric] for row in closed) if closed else None
            self.append(
                "day_value",
                {
                    "scope_id": scope,
                    "day_id": day_id,
                    "metric_id": self.definition("metric", {"name": metric, "unit": "Wh"}),
                },
                {
                    "value": known_sum if elapsed and len(closed) == expected else None,
                    "partial_value": known_sum,
                    "expected_intervals": expected,
                    "usable_intervals": len(closed),
                    "quality_id": self.quality(
                        "derived",
                        "full" if len(closed) == expected else "partial",
                        "unvalidated_flow",
                        "sum_available_archived_closed_flow_values:v1",
                    ),
                    "provenance_id": prov,
                },
            )
        self.append(
            "day_close",
            {"scope_id": scope, "day_id": day_id},
            {
                "state": ("CLOSED_COMPLETE" if complete else "CLOSED_PARTIAL")
                if elapsed
                else "OPEN",
                "checked_until_us": microseconds(data["ends_at"]),
                "manifest_def": self.definition(
                    "close_manifest",
                    {
                        "metric": "household",
                        "source": digest,
                        "replay": "not_certified",
                        "finance": "not_certified",
                    },
                ),
            },
        )

    def _days_and_prices(self, data: dict[str, Any], digest: str) -> None:
        scope = self.definition("scope", "home-battery")
        for key, row in data["days"].items():
            day_id = self.day(date.fromisoformat(key))
            for role, coverage in row.get("measurement_coverage", {}).items():
                for gap in coverage.get("gaps", []):
                    identity = [
                        role,
                        coverage.get("source_entity_id"),
                        gap["starts_at"],
                        gap["reason"],
                    ]
                    gap_id = sha256(encode(identity).encode()).hexdigest()
                    provenance = self.provenance(
                        digest, "archived_coverage:v1", microseconds(gap["ends_at"])
                    )
                    self.db.execute(
                        "INSERT INTO gap_episode VALUES(?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        "end_us=max(end_us,excluded.end_us)",
                        (
                            gap_id,
                            scope,
                            self.definition("metric", role),
                            microseconds(gap["starts_at"]),
                            microseconds(gap["ends_at"]),
                            "unknown",
                            "observed_not_recovered",
                            provenance,
                        ),
                    )
                    self.db.execute(
                        "INSERT OR IGNORE INTO gap_observation VALUES(?,?,?,?)",
                        (
                            gap_id,
                            digest,
                            microseconds(datetime.now(UTC)),
                            encode(
                                {
                                    "source": coverage.get("source_entity_id"),
                                    "gap": gap,
                                    "omitted_count": coverage.get("omitted_gap_count", 0),
                                }
                            ),
                        ),
                    )
            if "actual_energy_cost_eur" in row:
                prov = self.provenance(
                    digest, "legacy-finance-unchanged:v1", microseconds(row["captured_at"])
                )
                self.append(
                    "financial_result",
                    {
                        "scope_id": scope,
                        "day_id": day_id,
                        "metric_id": self.definition("metric", "legacy_finance"),
                    },
                    {
                        "amount_decimal": decimal_text(row["actual_energy_cost_eur"]),
                        "original_payload": encode(row),
                        "provenance_id": prov,
                        "quality_id": self.quality(
                            "model", "unknown", "legacy_available", "finalization_not_proven"
                        ),
                    },
                )
        for key, context in data.get("inputs", {}).items():
            day = date.fromisoformat(key)
            day_id = self.day(day)
            start, end = bounds(day)
            contract = self.definition("tariff_settings", context.get("settings"))
            prov = self.provenance(digest, "original-price-archive:v1", end)
            for price in context["prices"].values():
                a, b = microseconds(price["starts_at"]), microseconds(price["ends_at"])
                if not start <= a < end:
                    continue
                if not a < b <= end:
                    raise ValueError("tariff crosses local day")
                self.append(
                    "tariff",
                    {"scope_id": scope, "start_us": a, "end_us": b},
                    {
                        "day_id": day_id,
                        "import_decimal": decimal_text(price["value_eur_per_kwh"]),
                        "export_decimal": None,
                        "import_quality": self.quality("source", "available", "archived", None),
                        "export_quality": self.quality(
                            "unknown", "missing", "unknown", "not_separately_archived"
                        ),
                        "contract_def": contract,
                        "provenance_id": prov,
                    },
                )
