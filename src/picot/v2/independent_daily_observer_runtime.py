"""Passive runtime and persistence for independent daily observations."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter

from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    IndependentDailyReferenceAdapter,
)

SCHEMA_VERSION = 1
METHOD_VERSION = "v2-independent-daily-observer-runtime:v1"


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported daily observer value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class DailyObserverRuntimeOutcome:
    """Closed passive outcome for exactly one Planning Input snapshot."""

    snapshot_id: str
    run_id: str
    captured_at: datetime
    status: str
    reason: str | None
    duration_ms: float
    observation: DailyReferenceStrategyObservation | None
    observer_only: bool
    selection_permitted: bool
    commitment_permitted: bool
    method_version: str

    def __post_init__(self) -> None:
        if self.status not in {"completed", "blocked"}:
            raise ValueError("Daily observer runtime status must be completed or blocked.")
        if (self.observation is None) != (self.status == "blocked"):
            raise ValueError("Daily observer runtime status must match its observation.")
        if self.status == "blocked" and not self.reason:
            raise ValueError("Blocked daily observer runtime requires a reason.")
        if self.observation is not None and self.observation.snapshot_id != self.snapshot_id:
            raise ValueError("Daily observer runtime snapshot lineage must match.")
        if not self.observer_only or self.selection_permitted or self.commitment_permitted:
            raise ValueError("Daily observer runtime must remain passive.")


class DailyObserverResultStore:
    """Retain one full latest result plus append-only compact history."""

    def __init__(self, *, latest_path: Path, history_path: Path) -> None:
        self.latest_path = latest_path
        self.history_path = history_path

    def save(
        self,
        outcome: DailyObserverRuntimeOutcome,
        *,
        conversion_model: StorageConversionModel,
    ) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "outcome": asdict(outcome),
            "conversion_model": asdict(conversion_model),
        }
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.latest_path.with_name(f".{self.latest_path.name}.writing")
        temporary.write_text(
            json.dumps(payload, default=_json_value, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.latest_path)

        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    self._summary(outcome, conversion_model),
                    default=_json_value,
                    separators=(",", ":"),
                )
                + "\n"
            )

    @staticmethod
    def _summary(
        outcome: DailyObserverRuntimeOutcome,
        conversion_model: StorageConversionModel,
    ) -> dict[str, object]:
        observation = outcome.observation
        evaluation = (
            observation.observer_result.evaluation
            if observation is not None
            else None
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": outcome.snapshot_id,
            "run_id": outcome.run_id,
            "captured_at": outcome.captured_at,
            "status": outcome.status,
            "reason": outcome.reason,
            "duration_ms": outcome.duration_ms,
            "observer_only": outcome.observer_only,
            "selection_permitted": outcome.selection_permitted,
            "commitment_permitted": outcome.commitment_permitted,
            "best_observation_ids": (
                list(evaluation.best_candidate_ids)
                if evaluation is not None
                else []
            ),
            "evaluation_records": (
                [asdict(item) for item in evaluation.records]
                if evaluation is not None
                else []
            ),
            "conversion_model": asdict(conversion_model),
            "method_version": outcome.method_version,
        }


class IndependentDailyObserverRuntime:
    """Compute and persist a daily observation without affecting canonical flow."""

    def __init__(
        self,
        *,
        conversion_model: StorageConversionModel,
        store: DailyObserverResultStore,
    ) -> None:
        self.conversion_model = conversion_model
        self.store = store

    def observe(self, snapshot: PlanningInputSnapshot) -> DailyObserverRuntimeOutcome:
        started = perf_counter()
        observation: DailyReferenceStrategyObservation | None = None
        reason: str | None = None
        status = "completed"
        try:
            observation = IndependentDailyReferenceAdapter().observe(
                snapshot=snapshot,
                conversion_model=self.conversion_model,
            )
        except Exception as exc:
            status = "blocked"
            reason = str(exc) or exc.__class__.__name__
        outcome = DailyObserverRuntimeOutcome(
            snapshot_id=snapshot.snapshot_id,
            run_id=snapshot.run_id,
            captured_at=snapshot.captured_at,
            status=status,
            reason=reason,
            duration_ms=round((perf_counter() - started) * 1000.0, 3),
            observation=observation,
            observer_only=True,
            selection_permitted=False,
            commitment_permitted=False,
            method_version=METHOD_VERSION,
        )
        self.store.save(outcome, conversion_model=self.conversion_model)
        return outcome


class IndependentDailyObserverWorker:
    """Run observer work off the canonical thread and coalesce stale snapshots."""

    def __init__(
        self,
        runtime: IndependentDailyObserverRuntime,
        *,
        on_outcome: Callable[[DailyObserverRuntimeOutcome], None] | None = None,
        on_error: Callable[[PlanningInputSnapshot, Exception], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.on_outcome = on_outcome
        self.on_error = on_error
        self._lock = Lock()
        self._pending: PlanningInputSnapshot | None = None
        self._thread: Thread | None = None

    def submit(self, snapshot: PlanningInputSnapshot) -> None:
        """Retain the newest snapshot without delaying canonical execution."""
        with self._lock:
            self._pending = snapshot
            if self._thread is not None:
                return
            self._thread = Thread(
                target=self._drain,
                name="picot-v2-independent-daily-observer",
                daemon=True,
            )
            self._thread.start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                snapshot = self._pending
                self._pending = None
                if snapshot is None:
                    self._thread = None
                    return
            try:
                outcome = self.runtime.observe(snapshot)
                if self.on_outcome is not None:
                    self.on_outcome(outcome)
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(snapshot, exc)
