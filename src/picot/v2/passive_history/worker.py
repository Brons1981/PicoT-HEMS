"""Explicit one-shot history index worker; no imports from planning or HA."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import zlib
from pathlib import Path
from typing import Any

from .evidence import verify
from .storage import HistoryStore


def recheck_unavailable(store: HistoryStore, digests: list[str]) -> int:
    """Explicit selection only; never reset attempts or retry during discovery."""
    if not 1 <= len(digests) <= 16 or any(
        len(d) != 64 or any(c not in "0123456789abcdef" for c in d) for d in digests
    ):
        raise ValueError("select 1..16 valid evidence digests")
    with store.db:
        # Reserve queue capacity against another writer in the same transaction.
        store.db.execute("BEGIN IMMEDIATE")
        capacity = (
            64 - store.db.execute("SELECT count(*) FROM job WHERE state='pending'").fetchone()[0]
        )
        queued = 0
        for digest in dict.fromkeys(digests):
            if queued >= capacity:
                break
            queued += store.db.execute(
                "UPDATE job SET state='pending' WHERE digest=? AND state='source_unavailable'",
                (digest,),
            ).rowcount
        return queued


def discover(store: HistoryStore, *, scan_limit: int = 64, queue_limit: int = 64) -> int:
    """Durable bucket/name cursor, bounded bucket inventory and pending queue."""
    if not 1 <= scan_limit <= 256 or not 1 <= queue_limit <= 256:
        raise ValueError("invalid discovery budget")
    db = store.db
    with db:
        old = db.execute("SELECT value FROM history_meta WHERE key='discovery'").fetchone()
        bucket, after = json.loads(old[0]) if old else (0, "")
        capacity = (
            queue_limit - db.execute("SELECT count(*) FROM job WHERE state='pending'").fetchone()[0]
        )
        if capacity <= 0:
            return 0
        folder = store.root / "objects" / f"{bucket:02x}"
        names: list[str] = []
        if folder.exists():
            for entry in folder.iterdir():
                if len(names) >= 4096:
                    raise ValueError("discovery bucket limit; explicit intervention required")
                if entry.is_file() and not entry.is_symlink() and entry.name.endswith(".json.gz"):
                    names.append(entry.name)
        names.sort()
        selected = [name for name in names if name > after][: min(scan_limit, capacity)]
        for name in selected:
            digest = name.removesuffix(".json.gz")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                continue
            db.execute(
                "INSERT OR IGNORE INTO job(digest,path,state) VALUES(?,?,'pending')",
                (digest, str((folder / name).relative_to(store.root))),
            )
        cursor = (
            (bucket, selected[-1])
            if selected and selected[-1] != names[-1]
            else ((bucket + 1) % 256, "")
        )
        db.execute(
            "INSERT INTO history_meta VALUES('discovery',?) ON CONFLICT(key) "
            "DO UPDATE SET value=excluded.value",
            (json.dumps(cursor),),
        )
        return len(selected)


def process_batch(
    store: HistoryStore, *, limit: int = 4, free_reserve: int = 128 * 1024**2
) -> dict[str, int]:
    if not 1 <= limit <= 16:
        raise ValueError("invalid history batch size")
    result: dict[str, int] = {}
    for row in store.db.execute(
        "SELECT * FROM job WHERE state='pending' ORDER BY digest LIMIT ?", (limit,)
    ).fetchall():
        if shutil.disk_usage(store.root).free < free_reserve:
            result["paused_storage"] = 1
            break
        path = store.root / row["path"]
        source = store.definition("source", "passive-evidence-v1")
        store.db.commit()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(store.root / "objects"):
                raise ValueError("invalid evidence path")
            content = verify(path)
            data: Any = json.loads(content)
            del content
            if not isinstance(data, dict):
                raise ValueError("record must be an object")
            # Refuse nested nonfinite JSON without silently converting it to zero.
            with store.db:
                store.db.execute(
                    "INSERT INTO evidence_object VALUES(?,?,?,?,?,NULL,?) "
                    "ON CONFLICT(digest) DO UPDATE SET status=excluded.status",
                    (
                        row["digest"],
                        "source_record",
                        row["path"],
                        path.stat().st_size,
                        "verified_record",
                        source,
                    ),
                )
                store.import_record(data, row["digest"])
                store.observe(
                    row["digest"], "verified_record", "bytes_verified_not_replay_certified"
                )
                store.db.execute(
                    "UPDATE job SET state='done',attempts=attempts+1,reason=NULL WHERE digest=?",
                    (row["digest"],),
                )
            state = "done"
        except (MemoryError, RecursionError):
            state = "resource_deferred"
            with store.db:
                store.db.execute(
                    "UPDATE job SET state=?,attempts=attempts+1,reason=? WHERE digest=?",
                    (state, "memory_budget", row["digest"]),
                )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            EOFError,
            OverflowError,
            zlib.error,
        ) as exc:
            # BadGzipFile inherits OSError, but is evidence corruption, not I/O absence.
            state = (
                "source_unavailable"
                if isinstance(exc, OSError) and not isinstance(exc, gzip.BadGzipFile)
                else "invalid_record"
            )
            with store.db:
                store.db.execute(
                    "INSERT INTO evidence_object VALUES(?,?,?,?,?,NULL,?) "
                    "ON CONFLICT(digest) DO UPDATE SET status=excluded.status",
                    (row["digest"], "source_record", row["path"], None, state, source),
                )
                store.observe(row["digest"], state, type(exc).__name__)
                store.db.execute(
                    "UPDATE job SET state=?,attempts=attempts+1,reason=? WHERE digest=?",
                    (state, type(exc).__name__, row["digest"]),
                )
        result[state] = result.get(state, 0) + 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Opt-in one-shot passive history worker")
    parser.add_argument("root", type=Path)
    parser.add_argument("--memory-mib", type=int, default=128)
    parser.add_argument("--recheck-digest", action="append", default=[])
    args = parser.parse_args()
    # These limits belong exclusively to this explicitly started child process.
    import resource

    if not 64 <= args.memory_mib <= 256:
        parser.error("memory limit must be 64..256 MiB")
    if len(args.recheck_digest) > 16:
        parser.error("at most 16 explicitly selected rechecks")
    resource.setrlimit(resource.RLIMIT_AS, (args.memory_mib * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    store = HistoryStore(args.root)
    try:
        if args.recheck_digest:
            queued = recheck_unavailable(store, args.recheck_digest)
            print(json.dumps({"recheck_queued": queued, "processed": process_batch(store)}))
        else:
            discovered = discover(store)
            print(json.dumps({"discovered": discovered, "processed": process_batch(store)}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
