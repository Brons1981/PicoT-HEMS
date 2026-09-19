from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import date
from pathlib import Path
from threading import Event

import pytest

from picot.v2.passive_history.calendar import bounds, retention_tier
from picot.v2.passive_history.evidence import EvidenceRecorder, publish, verify
from picot.v2.passive_history.storage import HistoryStore
from picot.v2.passive_history.worker import discover, process_batch
from picot.v2.planning_incident_history import PlanningIncidentHistory


def spool(store: HistoryStore, value: object) -> Path:
    path = publish(store.root, json.dumps(value), free_reserve=0, storage_limit=64 * 1024**2)
    with store.db:
        store.db.execute(
            "INSERT OR IGNORE INTO job(digest,path,state) VALUES(?,?,'pending')",
            (path.name.removesuffix(".json.gz"), str(path.relative_to(store.root))),
        )
    return path


def test_capture_before_reduction_and_failure_preserves_incident_output(tmp_path):
    record = {
        "event": "synthetic",
        "poll": {"captured_at_utc": "2026-09-19T12:00:00+00:00", "padding": "x" * (9 * 1024**2)},
    }
    original = PlanningIncidentHistory(tmp_path / "original.jsonl")
    original._append(record)
    seen = []
    enabled = PlanningIncidentHistory(tmp_path / "enabled.jsonl", evidence_offer=seen.append)
    enabled._append(record)
    assert json.loads(seen[0]) == record
    assert enabled.path.read_bytes() == original.path.read_bytes()
    assert json.loads(enabled.path.read_text())["detail_level"] == "bounded"

    def fail(text):
        raise OSError("injected")

    failed = PlanningIncidentHistory(tmp_path / "failed.jsonl", evidence_offer=fail)
    failed._append(record)
    assert failed.path.read_bytes() == original.path.read_bytes()


def test_dutch_calendar_and_retention_edges():
    for day, expected in [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)]:
        start, end = bounds(day)
        assert (end - start) // 900_000_000 == expected
    assert retention_tier(date(2026, 9, 17), date(2026, 9, 19)) == "raw_replay"
    assert retention_tier(date(2026, 9, 16), date(2026, 9, 19)) == "all_quarters"
    assert retention_tier(date(2024, 2, 29), date(2029, 2, 28)) == "long_term"


def test_refuses_foreign_directory(tmp_path):
    (tmp_path / "unrelated").write_text("keep")
    with pytest.raises(ValueError, match="not owned"):
        HistoryStore(tmp_path)
    assert (tmp_path / "unrelated").read_text() == "keep"


def test_publication_dedup_and_digest_validation(tmp_path):
    store = HistoryStore(tmp_path / "history")
    text = json.dumps({"poll": {}, "value": "zon ☀"})
    path = publish(store.root, text, free_reserve=0, storage_limit=100000)
    assert verify(path) == text.encode()
    assert publish(store.root, text, free_reserve=0, storage_limit=100000) == path
    path.write_bytes(gzip.compress(b'{"wrong":true}'))
    with pytest.raises(ValueError, match="digest"):
        verify(path)
    with pytest.raises(ValueError, match="digest"):
        publish(store.root, text, free_reserve=0, storage_limit=100000)
    store.close()


def test_capture_active_record_and_contention(tmp_path, monkeypatch):
    entered, release = Event(), Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        raise OSError("injected")

    monkeypatch.setattr("picot.v2.passive_history.evidence.publish", blocked)
    recorder = EvidenceRecorder(tmp_path / "history", max_records=1)
    assert recorder.offer("{}") == "accepted"
    assert entered.wait(2)
    assert recorder.offer("{}") == "full"
    recorder._lock.acquire()
    try:
        assert recorder.offer("{}") == "contended"
    finally:
        recorder._lock.release()
    release.set()
    assert recorder.close()
    assert recorder.status()["pending"] == recorder.status()["reserved"] == 0
    assert recorder.status()["failed"] == 1


def test_discovery_bounded_resumable(tmp_path):
    store = HistoryStore(tmp_path / "history")
    for i in range(6):
        publish(store.root, json.dumps({"poll": {}, "n": i}), free_reserve=0, storage_limit=100000)
    for _ in range(300):
        discover(store, scan_limit=2, queue_limit=2)
        assert store.db.execute("SELECT count(*) FROM job WHERE state='pending'").fetchone()[0] <= 2
        process_batch(store, limit=1, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM evidence_object").fetchone()[0] == 6
    assert store.db.execute("SELECT sum(attempts) FROM job").fetchone()[0] == 6
    store.close()


def plan():
    return {
        "plan_id": "p",
        "snapshot_id": "s",
        "evaluation_id": "e",
        "valid_from": "2026-09-18T00:00:00+02:00",
        "valid_until": "2026-09-19T00:00:00+02:00",
    }


def poll(snapshot="s"):
    return {
        "poll": {
            "planning_input": {"snapshot_id": snapshot},
            "evaluation": {"evaluation_id": "e"},
            "execution_plan_set": {"plans": [{"plan_id": "p"}]},
        }
    }


def test_identity_discovery_order_and_later_context(tmp_path):
    store = HistoryStore(tmp_path / "history")
    spool(store, poll())
    process_batch(store, free_reserve=0)
    spool(store, {"execution_plans": {"p": plan()}})
    process_batch(store, free_reserve=0)
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 1
    spool(store, poll("later"))
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 1
    store.close()


def test_corrupt_recheck_revokes_link(tmp_path):
    store = HistoryStore(tmp_path / "history")
    spool(store, {"execution_plans": {"p": plan()}})
    process_batch(store, free_reserve=0)
    path = spool(store, poll())
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 1
    path.write_bytes(b"corrupt")
    with store.db:
        store.db.execute("UPDATE job SET state='pending'")
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 0
    store.close()


def test_tariff_revision_and_unknown_export(tmp_path):
    store = HistoryStore(tmp_path / "history")

    def source(price):
        return {
            "days": {},
            "inputs": {
                "2026-09-18": {
                    "settings": {},
                    "prices": {
                        "q": {
                            "starts_at": "2026-09-18T00:00:00+02:00",
                            "ends_at": "2026-09-18T00:15:00+02:00",
                            "value_eur_per_kwh": price,
                        }
                    },
                }
            },
        }

    for value in (0.2, -0.05):
        spool(store, source(value))
        process_batch(store, free_reserve=0)
    rows = store.db.execute(
        "SELECT revision,import_decimal,export_decimal FROM tariff ORDER BY revision"
    )
    assert [tuple(r) for r in rows] == [(1, "0.2", None), (2, "-0.05", None)]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("UPDATE tariff SET import_decimal='0'")
    store.close()


def archive(*, repaired=False):
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 9, 17, 22, tzinfo=UTC)
    rows = []
    for i in range(96):
        valid = repaired or i != 0
        rows.append(
            {
                "starts_at": (start + timedelta(minutes=15 * i)).isoformat(),
                "ends_at": (start + timedelta(minutes=15 * (i + 1))).isoformat(),
                "status": "derived" if valid else "invalid",
                "reason": None if valid else "source_coverage_incomplete",
                "household_energy_wh": 1 if valid else None,
                "energy_wh": {"grid_import": 1},
            }
        )
    return {
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(days=1)).isoformat(),
        "aligned_measurements": {"intervals": rows},
    }


def test_day_correction_preserves_partial_original_and_recheck_is_not_a_revision(tmp_path):
    store = HistoryStore(tmp_path / "history")
    old = spool(store, archive())
    process_batch(store, free_reserve=0)
    spool(store, archive(repaired=True))
    process_batch(store, free_reserve=0)
    metric = store.definition("metric", {"name": "household", "unit": "Wh"})
    rows = store.db.execute(
        "SELECT revision,value,partial_value,usable_intervals FROM day_value "
        "WHERE metric_id=? ORDER BY revision",
        (metric,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [(1, None, 95.0, 95), (2, 96.0, 96.0, 96)]
    assert [r[0] for r in store.db.execute("SELECT state FROM day_close ORDER BY revision")] == [
        "CLOSED_PARTIAL",
        "CLOSED_COMPLETE",
    ]
    with store.db:
        store.db.execute(
            "UPDATE job SET state='pending' WHERE digest=?", (old.name.removesuffix(".json.gz"),)
        )
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM day_close").fetchone()[0] == 2
    assert (
        store.db.execute(
            "SELECT count(*) FROM interval_value WHERE metric_id=?", (metric,)
        ).fetchone()[0]
        == 97
    )
    store.close()


def test_invalid_record_rolls_back_whole_day(tmp_path):
    store = HistoryStore(tmp_path / "history")
    data = archive()
    data["aligned_measurements"]["intervals"][1]["starts_at"] = "2026-09-15T00:00:00+00:00"
    spool(store, data)
    assert process_batch(store, free_reserve=0) == {"invalid_record": 1}
    assert store.db.execute("SELECT count(*) FROM interval_value").fetchone()[0] == 0
    store.close()


def test_low_disk_leaves_job_pending(tmp_path, monkeypatch):
    from collections import namedtuple

    store = HistoryStore(tmp_path / "history")
    spool(store, {"poll": {}})
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        "picot.v2.passive_history.worker.shutil.disk_usage", lambda _: usage(100, 100, 0)
    )
    assert process_batch(store) == {"paused_storage": 1}
    assert tuple(store.db.execute("SELECT state,attempts FROM job").fetchone()) == ("pending", 0)
    store.close()


def test_process_exit_does_not_commit_partial_job(tmp_path):
    import os
    import subprocess
    import sys

    store = HistoryStore(tmp_path / "history")
    spool(store, {"poll": {}})
    root = store.root
    store.close()
    code = """import os,sys
from pathlib import Path
from picot.v2.passive_history.storage import HistoryStore
from picot.v2.passive_history.worker import process_batch
s=HistoryStore(Path(sys.argv[1]))
def trace(sql):
 if sql.startswith("UPDATE job SET state='done'"): os._exit(73)
s.db.set_trace_callback(trace)
process_batch(s,free_reserve=0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        timeout=5,
        check=False,
    )
    assert result.returncode == 73
    store = HistoryStore(root)
    assert store.db.execute("SELECT count(*) FROM evidence_object").fetchone()[0] == 0
    assert tuple(store.db.execute("SELECT state,attempts FROM job").fetchone()) == ("pending", 0)
    assert process_batch(store, free_reserve=0) == {"done": 1}
    store.close()


def test_worker_entrypoint_is_explicit_and_process_bounded(tmp_path):
    import os
    import subprocess
    import sys

    store = HistoryStore(tmp_path / "history")
    spool(store, {"poll": {}})
    root = store.root
    store.close()
    result = subprocess.run(
        [sys.executable, "-m", "picot.v2.passive_history.worker", str(root)],
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["processed"] == {"done": 1}


def test_nonfinite_prices_do_not_become_decimal_strings():
    from picot.v2.passive_history.storage import decimal_text

    assert decimal_text(None) is None
    assert decimal_text("-0.0500") == "-0.0500"
    for value in (float("nan"), float("inf"), "NaN", True):
        with pytest.raises(ValueError):
            decimal_text(value)


def test_unavailable_evidence_requires_explicit_bounded_recheck(tmp_path, monkeypatch):
    import picot.v2.passive_history.worker as worker

    store = HistoryStore(tmp_path / "history")
    path = spool(store, {"poll": {}})
    digest = path.name.removesuffix(".json.gz")
    original = worker.verify
    with monkeypatch.context() as patcher:
        patcher.setattr(worker, "verify", lambda _: (_ for _ in ()).throw(OSError(5, "temporary")))
        assert process_batch(store, free_reserve=0) == {"source_unavailable": 1}
    store.close()
    store = HistoryStore(tmp_path / "history")
    assert original(path)
    for _ in range(256):
        discover(store)
    assert process_batch(store, free_reserve=0) == {}
    assert worker.recheck_unavailable(store, [digest]) == 1
    assert worker.recheck_unavailable(store, [digest]) == 0
    assert process_batch(store, free_reserve=0) == {"done": 1}
    assert tuple(store.db.execute("SELECT state,attempts FROM job").fetchone()) == ("done", 2)
    assert [
        r[0] for r in store.db.execute("SELECT status FROM evidence_observation ORDER BY id")
    ] == ["source_unavailable", "verified_record"]
    with pytest.raises(ValueError):
        worker.recheck_unavailable(store, [digest] * 17)
    store.close()


def test_recheck_does_not_revive_corrupt_evidence(tmp_path):
    from picot.v2.passive_history.worker import recheck_unavailable

    store = HistoryStore(tmp_path / "history")
    path = spool(store, {"poll": {}})
    path.write_bytes(b"not gzip")
    assert process_batch(store, free_reserve=0) == {"invalid_record": 1}
    assert recheck_unavailable(store, [path.name.removesuffix(".json.gz")]) == 0
    store.close()


def test_recheck_respects_queue_capacity_and_stops_after_repeated_absence(tmp_path):
    from picot.v2.passive_history.worker import recheck_unavailable

    store = HistoryStore(tmp_path / "history")
    path = spool(store, {"poll": {}})
    digest = path.name.removesuffix(".json.gz")
    path.unlink()
    assert process_batch(store, free_reserve=0) == {"source_unavailable": 1}
    with store.db:
        for i in range(64):
            store.db.execute(
                "INSERT INTO job(digest,path,state) VALUES(?,?,'pending')",
                (f"{i:064x}", "synthetic-missing"),
            )
    assert recheck_unavailable(store, [digest]) == 0
    with store.db:
        store.db.execute("DELETE FROM job WHERE path='synthetic-missing'")
    assert recheck_unavailable(store, [digest]) == 1
    assert process_batch(store, free_reserve=0) == {"source_unavailable": 1}
    assert process_batch(store, free_reserve=0) == {}
    assert tuple(store.db.execute("SELECT state,attempts FROM job").fetchone()) == (
        "source_unavailable",
        2,
    )
    store.close()


def test_temporary_unavailability_revokes_and_restores_plan_evidence(tmp_path):
    from picot.v2.passive_history.worker import recheck_unavailable

    store = HistoryStore(tmp_path / "history")
    spool(store, {"execution_plans": {"p": plan()}})
    process_batch(store, free_reserve=0)
    path = spool(store, poll())
    process_batch(store, free_reserve=0)
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 1
    digest = path.name.removesuffix(".json.gz")
    content = path.read_bytes()
    path.unlink()
    with store.db:
        store.db.execute("UPDATE job SET state='pending' WHERE digest=?", (digest,))
    assert process_batch(store, free_reserve=0) == {"source_unavailable": 1}
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 0
    path.write_bytes(content)
    assert recheck_unavailable(store, [digest]) == 1
    assert process_batch(store, free_reserve=0) == {"done": 1}
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 1
    store.close()


def test_explicit_recheck_cli(tmp_path):
    import os
    import subprocess
    import sys

    store = HistoryStore(tmp_path / "history")
    path = spool(store, {"poll": {}})
    content = path.read_bytes()
    path.unlink()
    assert process_batch(store, free_reserve=0) == {"source_unavailable": 1}
    path.write_bytes(content)
    root = store.root
    store.close()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "picot.v2.passive_history.worker",
            str(root),
            "--recheck-digest",
            path.name.removesuffix(".json.gz"),
        ],
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"recheck_queued": 1, "processed": {"done": 1}}
