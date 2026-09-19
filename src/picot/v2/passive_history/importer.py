"""Explicit, resumable diagnostic import into a separate history directory."""

from __future__ import annotations

import argparse
import gzip
import json
import zipfile
from hashlib import file_digest
from pathlib import Path

from .evidence import publish
from .storage import HistoryStore

MAX_RECORD = 32 * 1024**2
MEMBERS = {
    "picot_v2_active_plan_commitments.json",
    "picot_v2_financial_results.json",
    "picot_v2_grid_charge_review.json",
    "picot_v2_grid_charge_review_measurements_today.json.gz",
    "picot_v2_grid_charge_review_measurements_yesterday.json.gz",
}


def import_diagnostic(
    source: Path, store: HistoryStore, *, limit: int = 16, free_reserve: int = 128 * 1024**2
) -> dict[str, object]:
    """No extraction, HA reads, deletion or implicit processing. At most 16 new records."""
    if not 1 <= limit <= 16:
        raise ValueError("invalid import budget")
    with source.open("rb") as handle:
        digest = file_digest(handle, "sha256").hexdigest()
    key = "diagnostic:" + digest
    row = store.db.execute("SELECT value FROM history_meta WHERE key=?", (key,)).fetchone()
    member_index, offset = json.loads(row[0]) if row else (0, 0)
    imported = 0
    with zipfile.ZipFile(source) as archive:
        if len(archive.infolist()) > 256:
            raise ValueError("diagnostic member limit")
        names = sorted(
            n
            for n in archive.namelist()
            if n in MEMBERS
            or (n.startswith("picot_v2_planning_incident_history") and n.endswith(".jsonl"))
        )
        if len(set(names)) != len(names):
            raise ValueError("duplicate diagnostic member names")
        while member_index < len(names) and imported < limit:
            pending = store.db.execute("SELECT count(*) FROM job WHERE state='pending'").fetchone()[
                0
            ]
            if pending >= 64:
                break
            name = names[member_index]
            with archive.open(name) as raw:
                if name.endswith(".jsonl"):
                    raw.seek(offset)
                    body = raw.readline(MAX_RECORD + 2)
                    if len(body) > MAX_RECORD + 1:
                        raise ValueError("diagnostic record limit; import cursor unchanged")
                    next_offset = raw.tell()
                elif name.endswith(".gz"):
                    with gzip.GzipFile(fileobj=raw) as zipped:
                        body = zipped.read(MAX_RECORD + 1)
                    next_offset = 0
                else:
                    body = raw.read(MAX_RECORD + 1)
                    next_offset = 0
            if len(body) > MAX_RECORD:
                raise ValueError("diagnostic record limit; import cursor unchanged")
            if body:
                path = publish(
                    store.root,
                    body.decode("utf-8").rstrip("\r\n"),
                    free_reserve=free_reserve,
                    storage_limit=512 * 1024**2,
                )
                with store.db:
                    store.db.execute(
                        "INSERT OR IGNORE INTO job(digest,path,state) VALUES(?,?,'pending')",
                        (path.name.removesuffix(".json.gz"), str(path.relative_to(store.root))),
                    )
                    position = (
                        (member_index, next_offset)
                        if name.endswith(".jsonl")
                        else (member_index + 1, 0)
                    )
                    store.db.execute(
                        "INSERT INTO history_meta VALUES(?,?) ON CONFLICT(key) "
                        "DO UPDATE SET value=excluded.value",
                        (key, json.dumps(position)),
                    )
                member_index, offset = position
                imported += 1
            else:
                member_index, offset = member_index + 1, 0
                with store.db:
                    store.db.execute(
                        "INSERT INTO history_meta VALUES(?,?) ON CONFLICT(key) "
                        "DO UPDATE SET value=excluded.value",
                        (key, json.dumps((member_index, offset))),
                    )
    return {"source_sha256": digest, "imported": imported, "complete": member_index == len(names)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import at most 16 diagnostic records; opt-in only"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    store = HistoryStore(args.root)
    try:
        print(json.dumps(import_diagnostic(args.source, store)))
    finally:
        store.close()


if __name__ == "__main__":
    main()
