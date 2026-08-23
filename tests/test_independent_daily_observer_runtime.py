from __future__ import annotations

import json
from dataclasses import replace
from threading import Event
from typing import cast

from picot.v2.independent_daily_observer_runtime import (
    DailyObserverResultStore,
    DailyObserverRuntimeOutcome,
    IndependentDailyObserverRuntime,
    IndependentDailyObserverWorker,
)
from test_independent_daily_reference_adapter import _conversion, _snapshot


def _runtime(tmp_path):
    return IndependentDailyObserverRuntime(
        conversion_model=_conversion(),
        store=DailyObserverResultStore(
            latest_path=tmp_path / "latest.json",
            history_path=tmp_path / "history.jsonl",
        ),
    )


def test_runtime_persists_closed_observation_without_control_authority(tmp_path) -> None:
    outcome = _runtime(tmp_path).observe(_snapshot(maximum_soc=0.7))

    assert outcome.status == "completed"
    assert outcome.observation is not None
    assert outcome.observer_only is True
    assert outcome.selection_permitted is False
    assert outcome.commitment_permitted is False
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["outcome"]["snapshot_id"] == "snapshot"
    assert latest["outcome"]["status"] == "completed"
    assert latest["conversion_model"]["charge_efficiency"] == 1.0
    history = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history) == 1
    summary = json.loads(history[0])
    assert summary["best_observation_ids"]
    assert summary["evaluation_records"]


def test_runtime_persists_blocked_input_without_raising_into_canonical_flow(
    tmp_path,
) -> None:
    snapshot = replace(_snapshot(maximum_soc=0.7), price_points=())

    outcome = _runtime(tmp_path).observe(snapshot)

    assert outcome.status == "blocked"
    assert outcome.observation is None
    assert outcome.reason == "daily_tariff_prices_missing"
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["outcome"]["status"] == "blocked"
    assert latest["outcome"]["selection_permitted"] is False
    assert latest["outcome"]["commitment_permitted"] is False


def test_latest_result_is_replaced_while_history_remains_append_only(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    runtime.observe(_snapshot(maximum_soc=0.7))
    runtime.observe(replace(_snapshot(maximum_soc=0.7), price_points=()))

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    history = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert latest["outcome"]["status"] == "blocked"
    assert len(history) == 2


def test_worker_does_not_block_canonical_caller_and_keeps_latest_snapshot() -> None:
    started = Event()
    release = Event()
    completed = Event()
    observed: list[str] = []

    class BlockingRuntime:
        def observe(self, snapshot):
            observed.append(snapshot.strategy_id)
            started.set()
            release.wait(timeout=2.0)
            if len(observed) == 2:
                completed.set()

    first = _snapshot(maximum_soc=0.7)
    second = replace(first, strategy_id="strategy-two")
    third = replace(first, strategy_id="strategy-three")
    worker = IndependentDailyObserverWorker(
        cast(IndependentDailyObserverRuntime, BlockingRuntime())
    )

    worker.submit(first)
    assert started.wait(timeout=1.0)
    worker.submit(second)
    worker.submit(third)
    assert observed == [first.strategy_id]
    release.set()
    assert completed.wait(timeout=2.0)
    assert observed == [first.strategy_id, "strategy-three"]


def test_worker_publishes_completed_outcome_without_control_coupling(tmp_path) -> None:
    published: list[DailyObserverRuntimeOutcome] = []
    completed = Event()

    def capture(outcome: DailyObserverRuntimeOutcome) -> None:
        published.append(outcome)
        completed.set()

    worker = IndependentDailyObserverWorker(
        _runtime(tmp_path),
        on_outcome=capture,
    )

    worker.submit(_snapshot(maximum_soc=0.7))

    assert completed.wait(timeout=2.0)
    assert len(published) == 1
    assert published[0].observer_only is True
    assert published[0].selection_permitted is False
    assert published[0].commitment_permitted is False
