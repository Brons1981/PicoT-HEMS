"""Export progress measures actual archived bytes/rows, not elapsed time."""

import io
import sqlite3
import zipfile
from datetime import UTC, datetime

from picot.v2.diagnostic_downloads import diagnostic_zip
from picot_energy_devices.diagnostics import DiagnosticsRecorder


def test_hems_reports_chunks_and_accounts_for_live_file_growth(tmp_path):
    path = tmp_path / "large.jsonl"
    original = b"a" * (2 * 1024 * 1024 + 7)
    path.write_bytes(original)
    updates = []

    def progress(done, total, message):
        updates.append((done, total, message))
        if done == 0:
            with path.open("ab") as output:
                output.write(b"new live data")

    result = diagnostic_zip((path,), progress=progress)
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.read(path.name) == original + b"new live data"
    final_size = len(original) + len(b"new live data")
    assert [item[0] for item in updates] == [0, 1048576, 2097152, final_size, final_size]
    assert updates[0][1] == len(original)
    assert updates[-1][1] == final_size
    assert all(done <= total for done, total, _ in updates)


def test_energy_progress_counts_snapshot_and_batches_rows(tmp_path):
    now = datetime.now(UTC)
    recorder = DiagnosticsRecorder(tmp_path / "telemetry.sqlite3", options={})
    recorder.close()
    with sqlite3.connect(recorder.path) as db:
        db.executemany("INSERT INTO samples VALUES (?, ?, ?, ?)",
                       [(i, "regulation", now.timestamp(), "{}") for i in range(2501)])
    updates = []

    def progress(done, total, message):
        updates.append((done, total, message))
        if done == 0:
            # A concurrent WAL write must not affect either the count or exported rows.
            with sqlite3.connect(recorder.path) as db:
                db.execute("INSERT INTO events(stamp, kind, payload) VALUES (?, ?, ?)",
                           (now.timestamp(), "late", "{}"))

    result = recorder.export_zip(now=now, progress=progress)
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert len(archive.read("measurements.jsonl").splitlines()) == 2501
        assert b'"late"' not in archive.read("events.jsonl")
    assert [item[0] for item in updates] == [0, 1000, 2000, 2502]
    assert all(item[1] == 2502 for item in updates)
