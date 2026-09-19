"""Standalone Linux probe; synthetic evidence only, no planner or HA connection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from picot.v2.passive_history.evidence import EvidenceRecorder
from picot.v2.passive_history.storage import HistoryStore
from picot.v2.passive_history.worker import discover, process_batch


def phase(name: str, root: Path) -> dict[str, Any]:
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2 if name == "index" else 5,) * 2)
    cpu = time.process_time()
    started = time.monotonic()
    result: dict[str, Any] = {"phase": name}
    if name == "index":
        store = HistoryStore(root, database_limit=8 * 1024**2)
        try:
            for _ in range(256):
                discover(store)
            result["processed"] = process_batch(store, limit=4)
            result["remaining_pending"] = store.db.execute(
                "SELECT count(*) FROM job WHERE state='pending'"
            ).fetchone()[0]
            result["integrity"] = store.db.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            store.close()
    else:
        # Prepare distinct encoded records before measuring; capture receives existing text.
        payload = os.urandom(128 * 1024).hex()
        records = [json.dumps({"poll": {}, "probe": i, "padding": payload}) for i in range(4)]
        recorder = EvidenceRecorder(root, storage_limit=8 * 1024**2) if name == "capture" else None
        delays: list[float] = []
        offer_ms: list[float] = []
        outcomes: list[str] = []
        start = time.monotonic()
        try:
            # Same 20-Hz heartbeat for four seconds in two separate processes.
            for tick in range(80):
                due = start + tick * 0.05
                time.sleep(max(0, due - time.monotonic()))
                delays.append(max(0, time.monotonic() - due) * 1000)
                if recorder and tick % 20 == 0:
                    before = time.perf_counter()
                    outcomes.append(recorder.offer(records[tick // 20]))
                    offer_ms.append((time.perf_counter() - before) * 1000)
            result["heartbeat_samples"] = len(delays)
            result["heartbeat_p95_ms"] = sorted(delays)[75]
            result["heartbeat_max_ms"] = max(delays)
            result["offer_max_ms"] = max(offer_ms, default=0)
            result["offers"] = outcomes
        finally:
            if recorder:
                result["capture_stopped"] = recorder.close(timeout=2)
                result["capture_status"] = recorder.status()
    result["wall_seconds"] = time.monotonic() - started
    result["cpu_seconds"] = time.process_time() - cpu
    result["peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-parent", type=Path)
    parser.add_argument("--phase", choices=("baseline", "capture", "index"))
    parser.add_argument("--probe-root", type=Path)
    args = parser.parse_args()
    if args.phase:
        if args.probe_root is None:
            parser.error("internal phase requires probe root")
        print(json.dumps(phase(args.phase, args.probe_root)))
        return
    if args.scratch_parent is None or not args.scratch_parent.is_dir():
        parser.error("--scratch-parent must be an existing separate test directory")
    if platform.system() != "Linux":
        parser.error("this resource probe targets Linux")
    if shutil.disk_usage(args.scratch_parent).free < 512 * 1024**2:
        parser.error("at least 512 MiB free space required")
    result: dict[str, Any] = {
        "purpose": "synthetic_probe_not_live_planner_certification",
        "python": platform.python_version(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "payload_bytes_approx": 256 * 1024,
        "phases": [],
    }
    import picot.v2.passive_history.evidence as evidence

    package = Path(evidence.__file__).parent
    result["source_sha256"] = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in ("evidence.py", "worker.py", "storage.py")
    }
    with tempfile.TemporaryDirectory(prefix="picot-history-probe-", dir=args.scratch_parent) as d:
        for name in ("baseline", "capture", "index"):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--phase",
                name,
                "--probe-root",
                str(Path(d) / "history"),
            ]
            try:
                child = subprocess.run(
                    command, capture_output=True, text=True, timeout=15, check=False
                )
            except subprocess.TimeoutExpired:
                result["phases"].append({"phase": name, "failure": "timeout_child_stopped"})
                break
            if child.returncode:
                result["phases"].append(
                    {"phase": name, "exit_code": child.returncode, "stderr": child.stderr[-2000:]}
                )
                break
            measurement = json.loads(child.stdout)
            result["phases"].append(measurement)
            if measurement.get("capture_stopped") is False:
                break
        result["temporary_file_bytes"] = sum(
            p.stat().st_size for p in Path(d).rglob("*") if p.is_file()
        )
    phases_complete = len(result["phases"]) == 3 and not any(
        "failure" in p or "exit_code" in p or p.get("capture_stopped") is False
        for p in result["phases"]
    )
    result["workload_complete"] = bool(
        phases_complete
        and result["phases"][1].get("capture_status", {}).get("published") == 4
        and result["phases"][2].get("processed") == {"done": 4}
        and result["phases"][2].get("remaining_pending") == 0
        and result["phases"][2].get("integrity") == "ok"
    )
    print(json.dumps(result, indent=2))
    if not result["workload_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
