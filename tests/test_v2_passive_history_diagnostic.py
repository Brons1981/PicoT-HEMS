"""Optional real diagnostic replay; fixture stays outside the repository."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from hashlib import file_digest
from pathlib import Path

import pytest

from picot.v2.passive_history.importer import import_diagnostic
from picot.v2.passive_history.retention import compact_copy, preview, tables
from picot.v2.passive_history.storage import HistoryStore
from picot.v2.passive_history.worker import process_batch


@pytest.mark.skipif(
    not os.environ.get("PICOT_TEST_DIAGNOSTIC"), reason="external diagnostic fixture"
)
def test_september_19_diagnostic_preserves_88_quarters_and_seven_plan_matches(tmp_path):
    source = Path(os.environ["PICOT_TEST_DIAGNOSTIC"])
    with source.open("rb") as f:
        before = file_digest(f, "sha256").hexdigest()
    store = HistoryStore(tmp_path / "history")
    for _ in range(100):
        result = import_diagnostic(source, store, free_reserve=0)
        for _ in range(4):
            process_batch(store, free_reserve=0)
        pending = store.db.execute("SELECT count(*) FROM job WHERE state='pending'").fetchone()[0]
        if result["complete"] and not pending:
            break
    else:
        pytest.fail("bounded import did not finish")
    assert store.db.execute("SELECT count(*) FROM job WHERE state<>'done'").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM plan_evidence").fetchone()[0] == 171
    assert store.db.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 7
    assert store.db.execute("SELECT count(*) FROM tariff").fetchone()[0] == 288
    assert (
        store.db.execute("SELECT count(*) FROM tariff WHERE export_decimal IS NOT NULL").fetchone()[
            0
        ]
        == 0
    )
    metric = store.definition("metric", {"name": "household", "unit": "Wh"})
    row = store.db.execute(
        "SELECT value,partial_value,usable_intervals FROM day_value v "
        "JOIN local_day d ON d.id=v.day_id WHERE d.local_date=? AND metric_id=?",
        ("2026-09-18", metric),
    ).fetchone()
    assert row["value"] is None
    assert row["usable_intervals"] == 88
    assert row["partial_value"] == pytest.approx(6120.070153740213)
    counts = (
        store.db.execute("SELECT count(*) FROM job").fetchone()[0],
        store.db.execute("SELECT count(*) FROM day_value").fetchone()[0],
    )
    assert import_diagnostic(source, store, free_reserve=0)["imported"] == 0
    assert process_batch(store, free_reserve=0) == {}
    assert counts == (
        store.db.execute("SELECT count(*) FROM job").fetchone()[0],
        store.db.execute("SELECT count(*) FROM day_value").fetchone()[0],
    )
    assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
    store.close()
    # Age the imported copy only. Real dates, evidence and source ZIP stay intact.
    root = tmp_path / "history"
    report = preview(root, date(2026, 12, 18))
    output = tmp_path / "comparison.sqlite"
    compact_copy(root, output, date(2026, 12, 18), report["token"], free_reserve=0)
    with sqlite3.connect(root / "history.sqlite") as original, sqlite3.connect(output) as copy:
        for table in tables(original):
            if table in {"interval_value", "definition", "history_meta", "retention_batch"}:
                continue
            assert (
                copy.execute(f'SELECT * FROM "{table}"').fetchall()
                == original.execute(f'SELECT * FROM "{table}"').fetchall()
            ), table
        assert (
            copy.execute("SELECT * FROM interval_value WHERE metric_id=?", (metric,)).fetchall()
            == original.execute(
                "SELECT * FROM interval_value WHERE metric_id=?", (metric,)
            ).fetchall()
        )
        assert copy.execute("SELECT count(*) FROM usable_plan_objects").fetchone()[0] == 7
        assert copy.execute("SELECT count(*) FROM tariff").fetchone()[0] == 288
        print(
            "retention diagnostic omitted",
            report["omit_intervals"],
            "source bytes",
            (root / "history.sqlite").stat().st_size,
            "projection bytes",
            output.stat().st_size,
        )
    with source.open("rb") as f:
        assert file_digest(f, "sha256").hexdigest() == before
