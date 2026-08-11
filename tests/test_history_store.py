from datetime import UTC, datetime, timedelta

from picot.addon.history_store import HistoryStore


def test_history_store_persists_jsonl(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime.now(UTC)
    store.append({"event": "picot_goodwe_snapshot", "observed_at": now.isoformat()})
    assert "picot_goodwe_snapshot" in path.read_text(encoding="utf-8")


def test_history_store_keeps_full_detail_for_72_hours(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    sample_time = now - timedelta(hours=48)
    path.write_text(
        "\n".join(
            [
                '{"event":"picot_goodwe_snapshot","source_entity":"sensor.pv",'
                f'"observed_at":"{sample_time.isoformat()}","value":1}}',
                '{"event":"picot_goodwe_snapshot","source_entity":"sensor.pv",'
                f'"observed_at":"{(sample_time + timedelta(seconds=5)).isoformat()}",'
                '"value":2}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store.prune(now)

    content = path.read_text(encoding="utf-8")
    assert '"value":1' in content
    assert '"value":2' in content


def test_history_store_downsamples_after_72_hours_per_entity(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    sample_time = now - timedelta(days=5)
    path.write_text(
        "\n".join(
            [
                '{"event":"picot_goodwe_snapshot","source_entity":"sensor.pv_a",'
                f'"observed_at":"{sample_time.isoformat()}","marker":"a1"}}',
                '{"event":"picot_goodwe_snapshot","source_entity":"sensor.pv_a",'
                f'"observed_at":"{(sample_time + timedelta(seconds=5)).isoformat()}",'
                '"marker":"a2"}',
                '{"event":"picot_goodwe_snapshot","source_entity":"sensor.pv_b",'
                f'"observed_at":"{(sample_time + timedelta(seconds=5)).isoformat()}",'
                '"marker":"b1"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store.prune(now)

    content = path.read_text(encoding="utf-8")
    assert '"marker":"a1"' in content
    assert '"marker":"a2"' not in content
    assert '"marker":"b1"' in content


def test_history_store_keeps_forensic_events_full_for_90_days(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    sample_time = now - timedelta(days=20)
    path.write_text(
        "\n".join(
            [
                '{"event":"picot_price_decision",'
                f'"evaluated_at":"{sample_time.isoformat()}","marker":"first"}}',
                '{"event":"picot_price_decision",'
                f'"evaluated_at":"{(sample_time + timedelta(seconds=5)).isoformat()}",'
                '"marker":"second"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store.prune(now)

    content = path.read_text(encoding="utf-8")
    assert '"marker":"first"' in content
    assert '"marker":"second"' in content


def test_history_store_prunes_records_older_than_90_days(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    old = now - timedelta(days=91)
    path.write_text(
        '{"event":"picot_runtime_error","observed_at":"%s"}\n' % old.isoformat(),
        encoding="utf-8",
    )

    store.prune(now)

    assert path.read_text(encoding="utf-8") == ""


def test_history_store_iter_range_returns_only_selected_period(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    before = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
    inside = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)
    after = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
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
            datetime(2026, 8, 10, 20, 0, tzinfo=UTC),
            datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        )
    )

    assert [record["marker"] for record in records] == [22]
