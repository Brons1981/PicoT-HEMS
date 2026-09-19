"""Bounded synthetic 1/2/4/8 MiB capture/index overlap probe; no planner connection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import picot.v2.passive_history.evidence as evidence
from picot.v2.passive_history.storage import HistoryStore
from picot.v2.passive_history.worker import discover, process_batch

SIZES = (1, 2, 4, 8)


def records() -> list[str]:
    result = []
    for mib in SIZES:
        rows: list[str] = []
        size = 0
        while size < mib * 1024**2:
            row = json.dumps({"sequence": len(rows), "sample": os.urandom(512).hex()})
            rows.append(row)
            size += len(row) + 1
        result.append('{"poll":{},"synthetic_samples":[' + ",".join(rows) + "]}")
    return result


def child(
    name: str, root: Path, start: float, *, new_session: bool = False
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--phase",
            name,
            "--root",
            str(root),
            "--start",
            str(start),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=new_session,
    )


def collect(
    process: subprocess.Popen[str], timeout: float, *, process_group: bool = False
) -> dict[str, Any]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if process_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.communicate()
        return {"failure": "child_timeout"}
    if process.returncode:
        return {"failure": "child_exit", "exit_code": process.returncode, "stderr": stderr[-2000:]}
    result = json.loads(stdout)
    if not isinstance(result, dict):
        raise ValueError("invalid child report")
    return result


def phase(name: str, root: Path, start: float) -> dict[str, Any]:
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2 if name == "index" else 5,) * 2)
    cpu = time.process_time()
    wall = time.monotonic()
    result: dict[str, Any] = {"phase": name}
    if name == "index":
        store = HistoryStore(root, database_limit=8 * 1024**2)
        rounds = []
        try:
            for number in range(1, 5):
                time.sleep(max(0, start + 2 * number + 0.075 - time.monotonic()))
                began = time.monotonic()
                for _ in range(256):
                    discover(store)
                processed = process_batch(store, limit=4)
                rounds.append({"start": began, "end": time.monotonic(), "processed": processed})
            result["rounds"] = rounds
            result["jobs"] = dict(store.db.execute("SELECT state,count(*) FROM job GROUP BY state"))
            result["integrity"] = store.db.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            store.close()
    else:
        payloads = records()
        publications: list[dict[str, Any]] = []
        original = evidence.publish

        def timed_publish(*args: Any, **kwargs: Any) -> Path:
            began = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                publications.append({"start": began, "end": time.monotonic()})

        recorder = None
        worker = None
        if name == "concurrent":
            evidence.publish = timed_publish
            recorder = evidence.EvidenceRecorder(root, storage_limit=64 * 1024**2)
        start = time.monotonic() + 0.5
        delays = []
        offers = []
        try:
            if recorder:
                worker = child("index", root, start)
            for tick in range(164):
                due = start + tick * 0.05
                time.sleep(max(0, due - time.monotonic()))
                delays.append(max(0, time.monotonic() - due) * 1000)
                if recorder and tick in (0, 40, 80, 120):
                    before = time.perf_counter()
                    outcome = recorder.offer(payloads[tick // 40])
                    offers.append(
                        {
                            "bytes": len(payloads[tick // 40]),
                            "outcome": outcome,
                            "offer_ms": (time.perf_counter() - before) * 1000,
                        }
                    )
            result["heartbeat_p95_ms"] = sorted(delays)[155]
            result["heartbeat_max_ms"] = max(delays)
            result["heartbeat_samples"] = len(delays)
            result["offers"] = offers
        finally:
            if recorder:
                result["capture_stopped"] = recorder.close(timeout=2)
                result["capture_status"] = recorder.status()
            if worker:
                result["index"] = collect(worker, timeout=10)
            evidence.publish = original
        result["publications"] = publications
        rounds = result.get("index", {}).get("rounds", [])
        result["overlap_seconds"] = sum(
            max(0, min(p["end"], r["end"]) - max(p["start"], r["start"]))
            for p in publications
            for r in rounds
        )
    result["wall_seconds"] = time.monotonic() - wall
    result["cpu_seconds"] = time.process_time() - cpu
    result["peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-parent", type=Path)
    parser.add_argument("--phase", choices=("baseline", "concurrent", "index"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--start", type=float, default=0)
    args = parser.parse_args()
    if args.phase:
        if args.root is None:
            parser.error("internal phase requires root")
        print(json.dumps(phase(args.phase, args.root, args.start)))
        return
    if args.scratch_parent is None or not args.scratch_parent.is_dir():
        parser.error("an existing --scratch-parent is required")
    if shutil.disk_usage(args.scratch_parent).free < 512 * 1024**2:
        parser.error("at least 512 MiB free required")
    result: dict[str, Any] = {
        "purpose": "synthetic_large_overlap_not_planner_certification",
        "sizes_mib": SIZES,
        "python": sys.version.split()[0],
        "kernel": os.uname().release,
        "phases": [],
        "source_sha256": {
            name: hashlib.sha256((Path(evidence.__file__).parent / name).read_bytes()).hexdigest()
            for name in ("evidence.py", "worker.py", "storage.py")
        },
    }
    with tempfile.TemporaryDirectory(prefix="picot-large-probe-", dir=args.scratch_parent) as d:
        root = Path(d) / "history"
        for name in ("baseline", "concurrent"):
            measurement = collect(
                child(name, root, 0, new_session=True), timeout=25, process_group=True
            )
            result["phases"].append(measurement)
            if "failure" in measurement:
                break
        result["temporary_file_bytes"] = sum(
            p.stat().st_size for p in Path(d).rglob("*") if p.is_file()
        )
    last = result["phases"][-1]
    result["workload_complete"] = bool(
        len(result["phases"]) == 2
        and last.get("capture_stopped")
        and last.get("capture_status", {}).get("published") == 4
        and last.get("index", {}).get("jobs") == {"done": 4}
        and last.get("index", {}).get("integrity") == "ok"
    )
    result["overlap_observed"] = last.get("overlap_seconds", 0) > 0
    print(json.dumps(result, indent=2))
    if not result["workload_complete"] or not result["overlap_observed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
