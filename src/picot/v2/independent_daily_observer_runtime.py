"""Passive runtime and bounded persistence for independent daily observations."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
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

SCHEMA_VERSION = 2
METHOD_VERSION = "v2-independent-daily-observer-runtime:v2"
FULL_DETAIL_RETENTION = timedelta(hours=48)
COMPACT_RETENTION = timedelta(days=14)
MAX_LATEST_BYTES = 16 * 1024 * 1024
MAX_HISTORY_BYTES = 128 * 1024 * 1024


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported daily observer value: {type(value).__name__}")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=_json_value,
        separators=(",", ":"),
    ).encode("utf-8")


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
    """Retain bounded winner detail and compact run history.

    The live dashboard still receives the original in-memory outcome. Persistence
    deliberately avoids serialising every simulated trajectory for every losing
    candidate.
    """

    def __init__(
        self,
        *,
        latest_path: Path,
        history_path: Path,
        full_detail_retention: timedelta = FULL_DETAIL_RETENTION,
        compact_retention: timedelta = COMPACT_RETENTION,
        maximum_latest_bytes: int = MAX_LATEST_BYTES,
        maximum_history_bytes: int = MAX_HISTORY_BYTES,
    ) -> None:
        self.latest_path = latest_path
        self.history_path = history_path
        self.full_detail_retention = full_detail_retention
        self.compact_retention = compact_retention
        self.maximum_latest_bytes = maximum_latest_bytes
        self.maximum_history_bytes = maximum_history_bytes

    def save(
        self,
        outcome: DailyObserverRuntimeOutcome,
        *,
        conversion_model: StorageConversionModel,
    ) -> None:
        dashboard_view = self._dashboard_view(outcome)
        storage_policy = self._storage_policy()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "storage_policy": storage_policy,
            "outcome": self._outcome_metadata(outcome),
            "winner_detail": self._winner_detail(dashboard_view),
            "evaluation_records": self._evaluation_records(dashboard_view),
            "conversion_model": asdict(conversion_model),
        }
        encoded = _json_bytes(payload)
        if len(encoded) > self.maximum_latest_bytes:
            payload["winner_detail"] = self._bounded_winner_detail(
                payload["winner_detail"]
            )
            storage_policy["latest_detail_truncated"] = True
            encoded = _json_bytes(payload)
        if len(encoded) > self.maximum_latest_bytes:
            raise ValueError("daily_observer_latest_exceeds_storage_limit")
        self._atomic_write(self.latest_path, encoded)

        history = self._read_history()
        history.append(self._history_record(outcome, conversion_model, dashboard_view))
        history = self._prune_history(history, now=outcome.captured_at)
        self._write_history(history)

    def _storage_policy(self) -> dict[str, object]:
        return {
            "full_detail_hours": self.full_detail_retention.total_seconds() / 3600,
            "compact_retention_days": self.compact_retention.total_seconds() / 86400,
            "maximum_latest_bytes": self.maximum_latest_bytes,
            "maximum_history_bytes": self.maximum_history_bytes,
            "latest_detail_truncated": False,
        }

    @staticmethod
    def _dashboard_view(outcome: DailyObserverRuntimeOutcome) -> dict[str, object]:
        # Local import avoids a module cycle: the projection imports the outcome type.
        from picot.v2.independent_daily_dashboard import (
            build_daily_observer_dashboard_view,
        )

        return build_daily_observer_dashboard_view(outcome)

    @staticmethod
    def _outcome_metadata(outcome: DailyObserverRuntimeOutcome) -> dict[str, object]:
        return {
            "snapshot_id": outcome.snapshot_id,
            "run_id": outcome.run_id,
            "captured_at": outcome.captured_at,
            "status": outcome.status,
            "reason": outcome.reason,
            "duration_ms": outcome.duration_ms,
            "observer_only": outcome.observer_only,
            "selection_permitted": outcome.selection_permitted,
            "commitment_permitted": outcome.commitment_permitted,
            "method_version": outcome.method_version,
        }

    @staticmethod
    def _winner_detail(view: dict[str, object]) -> list[dict[str, object]]:
        candidates = view.get("candidates", [])
        if not isinstance(candidates, list):
            return []
        return [item for item in candidates if item.get("best_observation") is True]

    @staticmethod
    def _evaluation_records(view: dict[str, object]) -> list[dict[str, object]]:
        candidates = view.get("candidates", [])
        if not isinstance(candidates, list):
            return []
        omitted = {"intent_intervals", "scenarios"}
        return [
            {key: value for key, value in item.items() if key not in omitted}
            for item in candidates
        ]

    @staticmethod
    def _bounded_winner_detail(value: object) -> object:
        if not isinstance(value, list):
            return value
        return [
            {
                key: item
                for key, item in candidate.items()
                if key != "intent_intervals"
            }
            for candidate in value
        ]

    def _history_record(
        self,
        outcome: DailyObserverRuntimeOutcome,
        conversion_model: StorageConversionModel,
        dashboard_view: dict[str, object],
    ) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            **self._outcome_metadata(outcome),
            "objective": dashboard_view.get("objective"),
            "direction": dashboard_view.get("direction"),
            "best_observation_ids": dashboard_view.get("best_observation_ids", []),
            "winner_detail": self._winner_detail(dashboard_view),
            "evaluation_records": self._evaluation_records(dashboard_view),
            "conversion_model": asdict(conversion_model),
        }

    def _read_history(self) -> list[dict[str, object]]:
        if not self.history_path.exists():
            return []
        records: list[dict[str, object]] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def _prune_history(
        self,
        records: list[dict[str, object]],
        *,
        now: datetime,
    ) -> list[dict[str, object]]:
        detail_cutoff = now.astimezone(UTC) - self.full_detail_retention
        compact_cutoff = now.astimezone(UTC) - self.compact_retention
        retained: list[dict[str, object]] = []
        for record in records:
            captured_at = self._captured_at(record)
            if captured_at is None or captured_at < compact_cutoff:
                continue
            retained.append(record)
        retained.sort(
            key=lambda item: self._captured_at(item) or datetime.min.replace(tzinfo=UTC)
        )
        detailed_hours: set[datetime] = set()
        for index in range(len(retained) - 1, -1, -1):
            record = retained[index]
            captured_at = self._captured_at(record)
            if captured_at is None:
                continue
            hour = captured_at.replace(minute=0, second=0, microsecond=0)
            if captured_at < detail_cutoff or hour in detailed_hours:
                record = dict(record)
                record.pop("winner_detail", None)
                retained[index] = record
            else:
                detailed_hours.add(hour)
        while retained and self._history_size(retained) > self.maximum_history_bytes:
            retained.pop(0)
        return retained

    @staticmethod
    def _captured_at(record: dict[str, object]) -> datetime | None:
        value = record.get("captured_at")
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return None
            return value.astimezone(UTC)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _history_size(records: list[dict[str, object]]) -> int:
        return sum(len(_json_bytes(record)) + 1 for record in records)

    def _write_history(self, records: list[dict[str, object]]) -> None:
        encoded = b"".join(_json_bytes(record) + b"\n" for record in records)
        self._atomic_write(self.history_path, encoded)

    @staticmethod
    def _atomic_write(path: Path, encoded: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.writing")
        temporary.write_bytes(encoded)
        temporary.replace(path)


class IndependentDailyObserverRuntime:
    """Compute and persist a daily observation without affecting canonical flow."""

    def __init__(
        self,
        *,
        conversion_model: StorageConversionModel,
        store: DailyObserverResultStore,
        micro_charge_suppression_fraction: float = 0.01,
    ) -> None:
        self.conversion_model = conversion_model
        self.store = store
        self.micro_charge_suppression_fraction = micro_charge_suppression_fraction

    def observe(self, snapshot: PlanningInputSnapshot) -> DailyObserverRuntimeOutcome:
        started = perf_counter()
        observation: DailyReferenceStrategyObservation | None = None
        reason: str | None = None
        status = "completed"
        try:
            observation = IndependentDailyReferenceAdapter().observe(
                snapshot=snapshot,
                conversion_model=self.conversion_model,
                micro_charge_suppression_fraction=(
                    self.micro_charge_suppression_fraction
                ),
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
        on_settled: Callable[[PlanningInputSnapshot], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.on_outcome = on_outcome
        self.on_error = on_error
        self.on_settled = on_settled
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
            finally:
                if self.on_settled is not None:
                    try:
                        self.on_settled(snapshot)
                    except Exception as exc:
                        if self.on_error is not None:
                            self.on_error(snapshot, exc)
