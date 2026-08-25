from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.v2.independent_daily_observer_runtime import (
    DailyObserverResultStore,
    IndependentDailyObserverRuntime,
)


def _completed_outcome(tmp_path):
    runtime = IndependentDailyObserverRuntime(
        conversion_model=_conversion(),
        store=DailyObserverResultStore(
            latest_path=tmp_path / "seed-latest.json",
            history_path=tmp_path / "seed-history.jsonl",
        ),
    )
    return runtime.observe(_snapshot(maximum_soc=0.7))


def test_persistence_keeps_full_winner_but_compacts_losing_candidates(tmp_path) -> None:
    outcome = _completed_outcome(tmp_path)
    store = DailyObserverResultStore(
        latest_path=tmp_path / "latest.json",
        history_path=tmp_path / "history.jsonl",
    )

    store.save(outcome, conversion_model=_conversion())

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["schema_version"] == 2
    assert latest["storage_policy"]["full_detail_hours"] == 48
    assert latest["storage_policy"]["compact_retention_days"] == 14
    assert latest["winner_detail"]
    assert latest["winner_detail"][0]["intent_intervals"]
    assert latest["winner_detail"][0]["scenarios"]
    assert latest["evaluation_records"]
    assert all("intent_intervals" not in item for item in latest["evaluation_records"])
    assert all("scenarios" not in item for item in latest["evaluation_records"])


def test_history_keeps_48_hour_winner_detail_and_14_day_compact_results(
    tmp_path,
) -> None:
    outcome = _completed_outcome(tmp_path)
    store = DailyObserverResultStore(
        latest_path=tmp_path / "latest.json",
        history_path=tmp_path / "history.jsonl",
    )
    old_detail = replace(outcome, captured_at=outcome.captured_at - timedelta(days=3))
    expired = replace(outcome, captured_at=outcome.captured_at - timedelta(days=15))

    store.save(expired, conversion_model=_conversion())
    store.save(old_detail, conversion_model=_conversion())
    store.save(outcome, conversion_model=_conversion())

    history = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(history) == 2
    assert "winner_detail" not in history[0]
    assert history[0]["evaluation_records"]
    assert history[1]["winner_detail"]


def test_history_enforces_hard_byte_limit_by_dropping_oldest_runs(tmp_path) -> None:
    outcome = _completed_outcome(tmp_path)
    store = DailyObserverResultStore(
        latest_path=tmp_path / "latest.json",
        history_path=tmp_path / "history.jsonl",
        maximum_history_bytes=3_000_000,
    )

    for offset in range(8, -1, -1):
        store.save(
            replace(outcome, captured_at=outcome.captured_at - timedelta(hours=offset)),
            conversion_model=_conversion(),
        )

    assert (tmp_path / "history.jsonl").stat().st_size <= 3_000_000
    history = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert history
    assert history[-1]["captured_at"] == outcome.captured_at.isoformat()


def test_history_keeps_only_latest_full_winner_detail_per_hour(tmp_path) -> None:
    outcome = _completed_outcome(tmp_path)
    store = DailyObserverResultStore(
        latest_path=tmp_path / "latest.json",
        history_path=tmp_path / "history.jsonl",
    )

    for minutes in (0, 5, 10):
        store.save(
            replace(outcome, captured_at=outcome.captured_at + timedelta(minutes=minutes)),
            conversion_model=_conversion(),
        )

    history = [
        json.loads(line)
        for line in (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(history) == 3
    assert sum("winner_detail" in record for record in history) == 1
    assert "winner_detail" in history[-1]
