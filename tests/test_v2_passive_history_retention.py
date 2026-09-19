from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from test_v2_passive_history import archive, process_batch, spool

from picot.v2.passive_history.retention import compact_copy, preview
from picot.v2.passive_history.storage import HistoryStore


def seeded(tmp_path):
    store = HistoryStore(tmp_path / "source")
    spool(store, archive())
    process_batch(store, free_reserve=0)
    store.close()
    return tmp_path / "source"


def rows(db, table):
    return db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3,4,5").fetchall()


def test_preview_boundaries_and_copy_preserves_comparison(tmp_path):
    root = seeded(tmp_path)
    day = date(2026, 9, 18)
    for age in (0, 2, 3, 89):
        assert preview(root, day + timedelta(days=age))["omit_intervals"] == 0
    report = preview(root, day + timedelta(days=90))
    assert report["omit_intervals"] == 96
    original = sqlite3.connect(root / "history.sqlite")
    before = {t: rows(original, t) for t in ("interval_value", "day_value", "quality", "tariff")}
    output = tmp_path / "comparison.sqlite"
    compact_copy(root, output, day + timedelta(days=90), report["token"], free_reserve=0)
    copy = sqlite3.connect(output)
    assert copy.execute("SELECT count(*) FROM interval_value").fetchone()[0] == 96
    assert copy.execute("SELECT count(*) FROM compacted_interval_quality").fetchone()[0] == 96
    assert (
        copy.execute(
            "SELECT count(*) FROM compacted_interval_quality c "
            'JOIN quality q ON q.id=c.quality_id WHERE q.coverage="missing"'
        ).fetchone()[0]
        == 0
    )
    for table in ("day_value", "quality", "tariff"):
        assert rows(copy, table) == before[table]
    assert rows(original, "interval_value") == before["interval_value"]
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert copy.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        copy.execute("DELETE FROM interval_value")
    with pytest.raises(FileExistsError):
        compact_copy(root, output, day + timedelta(days=90), report["token"], free_reserve=0)
    copy.close()
    original.close()


def test_stale_preview_and_revision_are_conservative(tmp_path):
    root = seeded(tmp_path)
    today = date(2026, 12, 17)
    report = preview(root, today)
    store = HistoryStore(root)
    changed = archive()
    changed["aligned_measurements"]["intervals"][0]["energy_wh"]["grid_import"] = 2
    spool(store, changed)
    process_batch(store, free_reserve=0)
    store.close()
    with pytest.raises(ValueError, match="stale"):
        compact_copy(root, tmp_path / "stale.sqlite", today, report["token"], free_reserve=0)
    assert not (tmp_path / "stale.sqlite").exists()
    updated = preview(root, today)
    assert updated["omit_intervals"] == 0
    assert any(g["reason"] == "revisions_require_review" for g in updated["groups"])


def test_older_than_five_years_kept_and_low_disk_no_output(tmp_path):
    root = seeded(tmp_path)
    report = preview(root, date(2032, 1, 1))
    assert report["omit_intervals"] == 0
    assert any(g["reason"] == "review_required" for g in report["groups"])
    with pytest.raises(OSError, match="space"):
        compact_copy(
            root, tmp_path / "low.sqlite", date(2032, 1, 1), report["token"], free_reserve=10**30
        )
    assert not (tmp_path / "low.sqlite").exists()


@pytest.mark.parametrize("day,expected", [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)])
def test_dst_partial_quality_and_unknown_metric_survive(tmp_path, day, expected):
    from datetime import UTC, datetime

    from picot.v2.passive_history.calendar import bounds

    start, end = bounds(day)
    data = archive()
    template = data["aligned_measurements"]["intervals"][0]
    intervals = []
    for i in range(expected):
        intervals.append(
            {
                **template,
                "starts_at": datetime.fromtimestamp(
                    (start + i * 900_000_000) / 1e6, UTC
                ).isoformat(),
                "ends_at": datetime.fromtimestamp(
                    (start + (i + 1) * 900_000_000) / 1e6, UTC
                ).isoformat(),
                "energy_wh": {"grid_import": None if i == 0 else 1, "future_function": 3},
            }
        )
    data["starts_at"] = intervals[0]["starts_at"]
    data["ends_at"] = intervals[-1]["ends_at"]
    data["aligned_measurements"]["intervals"] = intervals
    store = HistoryStore(tmp_path / "source")
    spool(store, data)
    process_batch(store, free_reserve=0)
    store.close()
    root = tmp_path / "source"
    today = day + timedelta(days=90)
    report = preview(root, today)
    assert report["omit_intervals"] == expected
    output = tmp_path / "comparison.sqlite"
    compact_copy(root, output, today, report["token"], free_reserve=0)
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT quarter_count FROM local_day").fetchone()[0] == expected
        assert db.execute("SELECT count(*) FROM interval_value").fetchone()[0] == 2 * expected
        assert (
            db.execute(
                "SELECT count(*) FROM compacted_interval_quality c JOIN quality q "
                'ON q.id=c.quality_id WHERE q.coverage="missing"'
            ).fetchone()[0]
            == 1
        )
        assert db.execute("SELECT count(*) FROM day_value WHERE value IS NULL").fetchone()[0] == 2
        assert end - start == expected * 900_000_000


def test_copy_failure_does_not_publish_or_mutate_source(tmp_path, monkeypatch):
    from picot.v2.passive_history import retention

    root = seeded(tmp_path)
    today = date(2026, 12, 17)
    report = preview(root, today)
    original_writer = retention.write_projection

    def failed(*args):
        original_writer(*args)
        raise OSError("injected after completed transaction")

    monkeypatch.setattr(retention, "write_projection", failed)
    with pytest.raises(OSError, match="injected"):
        compact_copy(root, tmp_path / "failed.sqlite", today, report["token"], free_reserve=0)
    assert not (tmp_path / "failed.sqlite").exists()
    assert not list(tmp_path.glob(".history-projection-*"))
    assert preview(root, today) == report


def test_projection_cannot_be_used_by_history_writer(tmp_path):
    root = seeded(tmp_path)
    today = date(2026, 12, 17)
    report = preview(root, today)
    projected = tmp_path / "projected"
    projected.mkdir()
    (projected / "passive-history.owner").write_text("picot-passive-history-v1\n")
    compact_copy(root, projected / "history.sqlite", today, report["token"], free_reserve=0)
    before = (projected / "history.sqlite").read_bytes()
    with pytest.raises(ValueError, match="comparison projection"):
        HistoryStore(projected)
    assert (projected / "history.sqlite").read_bytes() == before
    with pytest.raises(ValueError, match="original history"):
        preview(projected, today)


def test_unproven_aggregate_is_retained(tmp_path):
    root = seeded(tmp_path)
    # Simulate a new independent day revision; no mutating immutable source rows.
    store = HistoryStore(root)
    metric = store.definition("metric", {"name": "grid_import", "unit": "Wh"})
    row = store.db.execute("SELECT * FROM day_value WHERE metric_id=?", (metric,)).fetchone()
    values = {
        k: row[k]
        for k in (
            "value",
            "partial_value",
            "expected_intervals",
            "usable_intervals",
            "quality_id",
            "provenance_id",
        )
    }
    values["provenance_id"] = store.provenance("new-source", "synthetic", 0)
    values["partial_value"] = 777
    with store.db:
        store.append("day_value", {k: row[k] for k in ("scope_id", "metric_id", "day_id")}, values)
    store.close()
    report = preview(root, date(2026, 12, 17))
    assert report["omit_intervals"] == 0
