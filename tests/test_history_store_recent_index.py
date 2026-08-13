from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from picot.addon.history_store import HistoryStore


def _event(at: datetime, *, value: int) -> dict[str, object]:
    return {
        "event": "picot_goodwe_snapshot",
        "observed_at": at.isoformat(),
        "status": "available",
        "solar_power_w": value,
    }


def test_recent_range_is_rebuilt_from_persistence_and_matches_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime(2026, 8, 13, 9, 35, tzinfo=timezone.utc)
    events = [
        _event(now - timedelta(minutes=30), value=100),
        _event(now - timedelta(minutes=10), value=200),
        _event(now - timedelta(minutes=1), value=300),
    ]
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    store = HistoryStore(path)

    result = list(store.iter_range(now - timedelta(minutes=15), now))
    assert [item["solar_power_w"] for item in result] == [200, 300]


def test_recent_range_does_not_require_rescanning_jsonl_after_startup(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime(2026, 8, 13, 9, 35, tzinfo=timezone.utc)
    path.write_text(json.dumps(_event(now - timedelta(minutes=5), value=100)) + "\n")
    store = HistoryStore(path)

    def fail_persisted_scan(start: datetime, end: datetime):
        raise AssertionError("recent range unexpectedly rescanned durable JSONL")
        yield  # pragma: no cover

    store._iter_persisted_range = fail_persisted_scan  # type: ignore[method-assign]
    store.append(_event(now, value=200))

    result = list(store.iter_range(now - timedelta(minutes=10), now))
    assert [item["solar_power_w"] for item in result] == [100, 200]


def test_older_range_falls_back_to_durable_history(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    now = datetime(2026, 8, 13, 9, 35, tzinfo=timezone.utc)
    old = now - timedelta(hours=3)
    path.write_text(
        json.dumps(_event(old, value=50))
        + "\n"
        + json.dumps(_event(now, value=200))
        + "\n",
        encoding="utf-8",
    )
    store = HistoryStore(path)

    result = list(store.iter_range(old - timedelta(minutes=1), old + timedelta(minutes=1)))
    assert [item["solar_power_w"] for item in result] == [50]
