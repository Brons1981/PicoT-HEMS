from datetime import datetime, timedelta, timezone

from picot.addon.history_store import HistoryStore


def test_history_store_persists_jsonl(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime.now(timezone.utc)
    store.append({"event": "picot_goodwe_snapshot", "observed_at": now.isoformat()})
    assert "picot_goodwe_snapshot" in path.read_text(encoding="utf-8")


def test_history_store_prunes_raw_after_seven_days_but_keeps_decisions(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=8)
    path.write_text(
        "{\"event\":\"picot_goodwe_snapshot\",\"observed_at\":\"%s\"}\n"
        "{\"event\":\"picot_price_decision\",\"evaluated_at\":\"%s\"}\n"
        % (old.isoformat(), old.isoformat()),
        encoding="utf-8",
    )
    store.prune(now)
    content = path.read_text(encoding="utf-8")
    assert "picot_goodwe_snapshot" not in content
    assert "picot_price_decision" in content


def test_history_store_iter_range_returns_only_selected_period(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    before = datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
    inside = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
    after = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
    for timestamp in (before, inside, after):
        store.append(
            {
                "event": "picot_goodwe_snapshot",
                "observed_at": timestamp.isoformat(),
                "marker": timestamp.hour,
            }
        )

    records = list(
        store.iter_range(
            datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc),
        )
    )

    assert [record["marker"] for record in records] == [22]
