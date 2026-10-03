"""Low-priority child process for calendar registration; no planning authority."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic

from picot.v2.household_calendar_history import (
    CALENDAR_DATABASE_PATH,
    CALENDAR_REPORT_PATH,
    HouseholdCalendarHistory,
)


def start_calendar_observer(
    options: Mapping[str, object], *, source: Path,
) -> subprocess.Popen[bytes] | None:
    """Start only an observer child; startup errors cannot stop the main runtime."""
    if options.get("household_calendar_history_enabled", True) is not True:
        return None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "picot.v2.household_calendar_runtime",
             "--source", str(source), "--database", str(CALENDAR_DATABASE_PATH),
             "--report", str(CALENDAR_REPORT_PATH), "--parent", str(os.getpid())],
            env={key: value for key, value in os.environ.items()
                 if key in {"PATH", "PYTHONPATH", "LANG", "TZ"}},
            stdin=subprocess.DEVNULL,
        )
        print(json.dumps({"event": "picot_household_calendar_started",
                          "pid": process.pid, "observer_only": True}), flush=True)
        return process
    except OSError as exc:
        print(json.dumps({"event": "picot_household_calendar_start_failed",
                          "error": type(exc).__name__, "observer_only": True}), flush=True)
        return None


def maintain_calendar_observer(
    process: subprocess.Popen[bytes] | None, options: Mapping[str, object], *,
    source: Path, now: float, restart_after: float,
) -> tuple[subprocess.Popen[bytes] | None, float]:
    """A dead observer gets a bounded retry; the caller never waits for its work."""
    if (options.get("household_calendar_history_enabled", True) is not True
            or now < restart_after or (process is not None and process.poll() is None)):
        return process, restart_after
    return start_calendar_observer(options, source=source), now + 300


def main() -> None:
    parser = argparse.ArgumentParser(description="Passive household calendar observer")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--parent", type=int, default=os.getppid())
    args = parser.parse_args()
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2,) * 2)
    os.nice(10)
    print(json.dumps({"event": "picot_household_calendar_worker_ready",
                      "observer_only": True,
                      "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
                      "nice": os.getpriority(os.PRIO_PROCESS, 0)}), flush=True)
    wait = Event()
    history: HouseholdCalendarHistory | None = None
    last_publication = 0.0
    last_caught_up = False
    while os.getppid() == args.parent:
        delay = 60.0
        try:
            if history is None:
                history = HouseholdCalendarHistory(args.database)
            progress = history.ingest_batch(args.source)
            caught_up = bool(progress["caught_up"])
            if (last_publication == 0 or monotonic() - last_publication >= 900
                    or (caught_up and not last_caught_up)):
                history.publish(args.report, now=datetime.now(UTC))
                last_publication = monotonic()
                print(json.dumps({"event": "picot_household_calendar_progress",
                                  "observer_only": True, "progress": progress}), flush=True)
            last_caught_up = caught_up
            if progress["state"] == "ready" and not caught_up:
                # Bounded backfill yields to the runtime between every transaction.
                delay = 1.0 if progress["consumed_lines"] else 60.0
        except (OSError, ValueError, sqlite3.Error, MemoryError) as exc:
            print(json.dumps({"event": "picot_household_calendar_error",
                              "error": type(exc).__name__, "observer_only": True}), flush=True)
            if history is not None:
                history.close()
                history = None
        wait.wait(delay)
    if history is not None:
        history.close()


if __name__ == "__main__":
    main()
