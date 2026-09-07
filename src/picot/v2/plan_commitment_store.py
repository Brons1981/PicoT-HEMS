"""Durable active execution commitment state required by V2ADR-052."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from picot.architecture_ownership import architecture_ownership
from picot.v2.daily_charge_assignment import (
    DailyChargeAssignment,
    DailyChargeRevisionReason,
    DailyChargeSegment,
    published_assignments,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("plan_store", __name__)
COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v9"
COMPARISON_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v7"
MATERIALITY_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v6"
TIMING_PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v5"
DEFECTIVE_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v4"
PREVIOUS_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v3"
EARLIER_COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v2"
LEGACY_COMMITMENT_METHOD_VERSION = "legacy-pre-household-simulation"


@dataclass(frozen=True, slots=True)
class CommittedPlanSegment:
    """Canonical segment retained as part of the durable incumbent path."""

    starts_at: datetime
    ends_at: datetime
    primitive: str
    source_policy: str | None
    storage_export_target_wh: float | None = None

    def __post_init__(self) -> None:
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("committed segment timestamps must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("committed segment start must precede end")
        if not self.primitive.strip():
            raise ValueError("committed segment primitive must be explicit")
        if self.source_policy is not None and not self.source_policy.strip():
            raise ValueError("committed segment source policy must be explicit")
        if self.storage_export_target_wh is not None:
            if self.storage_export_target_wh <= 0.0:
                raise ValueError("committed export target must be positive")
            if self.primitive != "discharge_at_power":
                raise ValueError("only committed discharge may carry an export target")


@dataclass(frozen=True, slots=True)
class CommittedHouseholdLoadInterval:
    """Frozen household forecast evidence used by the admitted plan."""

    interval_id: str
    starts_at: datetime
    ends_at: datetime
    expected_energy_wh: float
    confidence: float
    source_reference: str
    method_version: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.interval_id,
                self.source_reference,
                self.method_version,
            )
        ):
            raise ValueError("committed household-load lineage must be explicit")
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    "committed household-load timestamps must be timezone-aware"
                )
        if self.starts_at >= self.ends_at:
            raise ValueError("committed household-load interval must be positive")
        if self.expected_energy_wh < 0.0:
            raise ValueError("committed household energy must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("committed household confidence must be bounded")


@dataclass(frozen=True, slots=True)
class CommittedStorageEnergyCheckpoint:
    """Frozen lower/central/upper storage corridor for one plan checkpoint."""

    at: datetime
    lower_energy_wh: float
    central_energy_wh: float
    upper_energy_wh: float

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("committed storage checkpoint must be timezone-aware")
        if not (
            0.0
            <= self.lower_energy_wh
            <= self.central_energy_wh
            <= self.upper_energy_wh
        ):
            raise ValueError("committed storage corridor must be ordered")


@dataclass(frozen=True, slots=True)
class ActivePlanCommitment:
    execution_scope_id: str
    plan_id: str
    plan_revision: int
    primitive: str
    source_policy: str
    starts_at: datetime
    ends_at: datetime
    target_energy_wh: float
    selection_method_version: str = COMMITMENT_METHOD_VERSION
    planner_id: str = "canonical"
    schedule_id: str | None = None
    worst_case_financial_result_eur: float | None = None
    average_charge_window_price_eur_per_kwh: float | None = None
    minimum_confidence: float | None = None
    reserve_respected_across_scenarios: bool | None = None
    target_held_across_scenarios: bool | None = None
    minimum_storage_energy_at_horizon_end_wh: float | None = None
    segments: tuple[CommittedPlanSegment, ...] = ()
    selection_reason: str | None = None
    replaced_plan_id: str | None = None
    selected_at: datetime | None = None
    household_load_intervals: tuple[CommittedHouseholdLoadInterval, ...] = ()
    storage_energy_checkpoints: tuple[CommittedStorageEnergyCheckpoint, ...] = ()
    candidate_family: str | None = None
    pv_preservation_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.execution_scope_id,
                self.plan_id,
                self.primitive,
                self.source_policy,
                self.selection_method_version,
                self.planner_id,
            )
        ):
            raise ValueError("active plan commitment fields must be explicit")
        if self.plan_revision < 1:
            raise ValueError("plan revision must be positive")
        if self.target_energy_wh <= 0.0:
            raise ValueError("commitment target energy must be positive")
        for value in (self.starts_at, self.ends_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("commitment timestamps must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("commitment start must precede end")
        if self.schedule_id is not None and not self.schedule_id.strip():
            raise ValueError("commitment schedule id must be explicit")
        for evidence_value in (self.selection_reason, self.replaced_plan_id):
            if evidence_value is not None and not evidence_value.strip():
                raise ValueError("commitment replacement evidence must be explicit")
        if self.candidate_family is not None and not self.candidate_family.strip():
            raise ValueError("commitment candidate family must be explicit")
        if self.selected_at is not None:
            if (
                self.selected_at.tzinfo is None
                or self.selected_at.utcoffset() is None
            ):
                raise ValueError("commitment selection time must be timezone-aware")
            if self.selected_at >= self.ends_at:
                raise ValueError("commitment selection must precede plan end")
        if (
            self.household_load_intervals or self.storage_energy_checkpoints
        ) and self.selected_at is None:
            raise ValueError("commitment monitoring baselines require selection time")
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(self.segments, self.segments[1:], strict=False)
        ):
            raise ValueError("committed plan segments must not overlap")
        if self.minimum_confidence is not None and not (
            0.0 <= self.minimum_confidence <= 1.0
        ):
            raise ValueError("commitment confidence must be bounded")
        if (
            self.minimum_storage_energy_at_horizon_end_wh is not None
            and self.minimum_storage_energy_at_horizon_end_wh < 0.0
        ):
            raise ValueError("commitment horizon energy must be non-negative")
        if any(
            left.ends_at > right.starts_at
            for left, right in zip(
                self.household_load_intervals,
                self.household_load_intervals[1:],
                strict=False,
            )
        ):
            raise ValueError("committed household-load intervals must not overlap")
        checkpoint_times = tuple(
            checkpoint.at for checkpoint in self.storage_energy_checkpoints
        )
        if checkpoint_times != tuple(sorted(set(checkpoint_times))):
            raise ValueError(
                "committed storage checkpoints must be unique and ordered"
            )
        if self.pv_preservation_dates != tuple(
            sorted(set(self.pv_preservation_dates))
        ):
            raise ValueError("PV preservation dates must be unique and ordered")


def active_pv_preservation_dates(
    commitment: ActivePlanCommitment,
    *,
    captured_at: datetime,
) -> tuple[date, ...]:
    """Return active User Rule dates, including pre-DEV.235 commitments."""

    current_date = captured_at.date()
    derived = {
        segment.starts_at.date()
        for segment in commitment.segments
        if segment.primitive == "charge_at_power"
        and segment.starts_at.date() >= current_date
    }
    derived.update(
        item for item in commitment.pv_preservation_dates if item >= current_date
    )
    return tuple(sorted(derived))


class ActivePlanCommitmentStore:
    """Atomically persist at most one active commitment per execution scope."""

    def __init__(self, path: Path, *, incident_path: Path | None = None) -> None:
        self._path = path
        self._incident_path = incident_path

    def load(self, execution_scope_id: str) -> ActivePlanCommitment | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            commitments = payload["commitments"]
            raw = commitments.get(execution_scope_id)
            return _deserialize(raw) if raw is not None else None
        except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
            self._record_incident("commitment_store_unreadable", exc)
            return None

    def save(self, commitment: ActivePlanCommitment) -> None:
        payload = self._load_payload()
        serialized = asdict(commitment)
        serialized["starts_at"] = commitment.starts_at.isoformat()
        serialized["ends_at"] = commitment.ends_at.isoformat()
        serialized["selected_at"] = (
            commitment.selected_at.isoformat()
            if commitment.selected_at is not None
            else None
        )
        serialized["pv_preservation_dates"] = [
            item.isoformat() for item in commitment.pv_preservation_dates
        ]
        serialized["segments"] = [
            {
                "starts_at": segment.starts_at.isoformat(),
                "ends_at": segment.ends_at.isoformat(),
                "primitive": segment.primitive,
                "source_policy": segment.source_policy,
                "storage_export_target_wh": segment.storage_export_target_wh,
            }
            for segment in commitment.segments
        ]
        serialized["household_load_intervals"] = [
            {
                "interval_id": interval.interval_id,
                "starts_at": interval.starts_at.isoformat(),
                "ends_at": interval.ends_at.isoformat(),
                "expected_energy_wh": interval.expected_energy_wh,
                "confidence": interval.confidence,
                "source_reference": interval.source_reference,
                "method_version": interval.method_version,
            }
            for interval in commitment.household_load_intervals
        ]
        serialized["storage_energy_checkpoints"] = [
            {
                "at": checkpoint.at.isoformat(),
                "lower_energy_wh": checkpoint.lower_energy_wh,
                "central_energy_wh": checkpoint.central_energy_wh,
                "upper_energy_wh": checkpoint.upper_energy_wh,
            }
            for checkpoint in commitment.storage_energy_checkpoints
        ]
        payload["commitments"][commitment.execution_scope_id] = serialized
        self._write(payload)

    def load_daily_assignments(self) -> tuple[DailyChargeAssignment, ...]:
        """Load durable daily tasks without treating corrupt state as a new day."""
        payload = self._load_payload()
        try:
            records = payload.get("daily_assignments", {})
            if not isinstance(records, dict):
                raise ValueError("daily assignments must be an object")
            assignments = tuple(_deserialize_daily(item) for item in records.values())
            if any(key != item.assignment_id for key, item in zip(
                records, assignments, strict=True
            )):
                raise ValueError("daily assignment identity does not match its storage key")
            return assignments
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self._record_incident("daily_charge_state_unreadable", exc)
            raise ValueError("daily charge state unreadable; refusing to recreate tasks") from exc

    def reconcile_daily_publication(
        self, *, now: datetime, timezone: str, execution_scope_id: str,
        price_intervals: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[DailyChargeAssignment, ...]:
        """Create missing daily identities once, including after an offline start.

        This entry point consumes canonical price coverage; it neither selects
        windows nor binds legacy execution segments to the new main task.
        """
        existing = self.load_daily_assignments()
        reconciled = published_assignments(
            now=now, timezone=timezone, execution_scope_id=execution_scope_id,
            price_intervals=price_intervals, existing=existing,
        )
        previous = {a.assignment_id: a for a in existing}
        additions = tuple(a for a in reconciled if a.assignment_id not in previous)
        if additions:
            payload = self._load_payload()
            records = payload.setdefault("daily_assignments", {})
            for assignment in additions:
                records[assignment.assignment_id] = _serialize_daily(assignment)
            self._write(payload)
        return reconciled

    def save_daily_assignment(self, assignment: DailyChargeAssignment) -> None:
        """Persist one lifecycle transition using the existing single-writer store.

        A stale route or duplicate publication cannot reset completion. Active
        execution-plan resets intentionally do not remove daily goal history.
        """
        existing = {a.assignment_id: a for a in self.load_daily_assignments()}
        previous = existing.get(assignment.assignment_id)
        if previous == assignment:
            return
        if previous is not None:
            if previous.completed_at is not None:
                raise ValueError("completed daily assignment cannot be overwritten")
            if assignment.created_at != previous.created_at:
                raise ValueError("daily assignment creation identity cannot be replaced")
            if assignment.revision == previous.revision:
                expected = replace(previous, completed_at=assignment.completed_at,
                                   completion_evidence_id=assignment.completion_evidence_id,
                                   completion_segment_id=assignment.completion_segment_id)
                if assignment != expected:
                    raise ValueError("route changes require a new daily revision")
            elif assignment.revision != previous.revision + 1:
                raise ValueError("stale or skipped daily assignment revision")
            elif previous.revised_at is not None and (
                assignment.revised_at is None or assignment.revised_at < previous.revised_at
            ):
                raise ValueError("daily assignment revision time cannot move backwards")
        payload = self._load_payload()
        payload.setdefault("daily_assignments", {})[assignment.assignment_id] = _serialize_daily(
            assignment
        )
        self._write(payload)

    def clear(self, execution_scope_id: str) -> None:
        payload = self._load_payload()
        if payload["commitments"].pop(execution_scope_id, None) is not None:
            self._write(payload)

    def clear_all(self) -> tuple[ActivePlanCommitment, ...]:
        """Atomically remove all commitments and return the removed records."""

        payload = self._load_payload()
        removed = tuple(
            _deserialize(item)
            for item in payload["commitments"].values()
        )
        if removed:
            payload["commitments"] = {}
            self._write(payload)
        return removed

    def record_manual_reset(
        self,
        *,
        reset_id: str,
        removed: tuple[ActivePlanCommitment, ...],
    ) -> None:
        if not reset_id.strip():
            raise ValueError("reset_id must be explicit")
        self._record_incident(
            "manual_planning_reset_requested",
            ValueError(
                json.dumps(
                    {
                        "reset_id": reset_id,
                        "removed_plan_ids": [item.plan_id for item in removed],
                        "removed_scope_ids": [
                            item.execution_scope_id for item in removed
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        )

    def record_recovery_rejection(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("recovery rejection reason must be explicit")
        self._record_incident(
            "commitment_recovery_rejected",
            ValueError(reason),
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": 1, "commitments": {}}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("commitment state must be an object")
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported commitment schema")
            if not isinstance(payload.get("commitments"), dict):
                raise ValueError("commitments must be an object")
            return cast(dict[str, Any], payload)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            self._record_incident("commitment_store_write_refused", exc)
            raise ValueError("commitment state unreadable; refusing destructive reset") from exc

    def _write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    def _record_incident(self, code: str, exc: Exception) -> None:
        if self._incident_path is None:
            return
        fingerprint = sha256(
            f"{code}|{type(exc).__name__}|{exc}".encode()
        ).hexdigest()[:16]
        existing = (
            self._incident_path.read_text(encoding="utf-8")
            if self._incident_path.exists()
            else ""
        )
        if f'"fingerprint":"{fingerprint}"' in existing:
            return
        self._incident_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "code": code,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "fingerprint": fingerprint,
        }
        with self._incident_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def _deserialize(payload: dict[str, Any]) -> ActivePlanCommitment:
    return ActivePlanCommitment(
        execution_scope_id=str(payload["execution_scope_id"]),
        plan_id=str(payload["plan_id"]),
        plan_revision=int(payload["plan_revision"]),
        primitive=str(payload["primitive"]),
        source_policy=str(payload["source_policy"]),
        starts_at=datetime.fromisoformat(payload["starts_at"]),
        ends_at=datetime.fromisoformat(payload["ends_at"]),
        target_energy_wh=float(payload["target_energy_wh"]),
        selection_method_version=str(
            payload.get(
                "selection_method_version",
                LEGACY_COMMITMENT_METHOD_VERSION,
            )
        ),
        planner_id=str(payload.get("planner_id", "canonical")),
        schedule_id=(
            str(payload["schedule_id"])
            if payload.get("schedule_id") is not None
            else None
        ),
        worst_case_financial_result_eur=(
            float(payload["worst_case_financial_result_eur"])
            if payload.get("worst_case_financial_result_eur") is not None
            else None
        ),
        average_charge_window_price_eur_per_kwh=(
            float(payload["average_charge_window_price_eur_per_kwh"])
            if payload.get("average_charge_window_price_eur_per_kwh") is not None
            else None
        ),
        minimum_confidence=(
            float(payload["minimum_confidence"])
            if payload.get("minimum_confidence") is not None
            else None
        ),
        reserve_respected_across_scenarios=(
            bool(payload["reserve_respected_across_scenarios"])
            if payload.get("reserve_respected_across_scenarios") is not None
            else None
        ),
        target_held_across_scenarios=(
            bool(payload["target_held_across_scenarios"])
            if payload.get("target_held_across_scenarios") is not None
            else None
        ),
        minimum_storage_energy_at_horizon_end_wh=(
            float(payload["minimum_storage_energy_at_horizon_end_wh"])
            if payload.get("minimum_storage_energy_at_horizon_end_wh") is not None
            else None
        ),
        segments=tuple(
            CommittedPlanSegment(
                starts_at=datetime.fromisoformat(item["starts_at"]),
                ends_at=datetime.fromisoformat(item["ends_at"]),
                primitive=str(item["primitive"]),
                source_policy=(
                    str(item["source_policy"])
                    if item.get("source_policy") is not None
                    else None
                ),
                storage_export_target_wh=(
                    float(item["storage_export_target_wh"])
                    if item.get("storage_export_target_wh") is not None
                    else None
                ),
            )
            for item in payload.get("segments", ())
        ),
        selection_reason=(
            str(payload["selection_reason"])
            if payload.get("selection_reason") is not None
            else None
        ),
        replaced_plan_id=(
            str(payload["replaced_plan_id"])
            if payload.get("replaced_plan_id") is not None
            else None
        ),
        selected_at=(
            datetime.fromisoformat(payload["selected_at"])
            if payload.get("selected_at") is not None
            else None
        ),
        household_load_intervals=tuple(
            CommittedHouseholdLoadInterval(
                interval_id=str(item["interval_id"]),
                starts_at=datetime.fromisoformat(item["starts_at"]),
                ends_at=datetime.fromisoformat(item["ends_at"]),
                expected_energy_wh=float(item["expected_energy_wh"]),
                confidence=float(item["confidence"]),
                source_reference=str(item["source_reference"]),
                method_version=str(item["method_version"]),
            )
            for item in payload.get("household_load_intervals", ())
        ),
        storage_energy_checkpoints=tuple(
            CommittedStorageEnergyCheckpoint(
                at=datetime.fromisoformat(item["at"]),
                lower_energy_wh=float(item["lower_energy_wh"]),
                central_energy_wh=float(item["central_energy_wh"]),
                upper_energy_wh=float(item["upper_energy_wh"]),
            )
            for item in payload.get("storage_energy_checkpoints", ())
        ),
        candidate_family=(
            str(payload["candidate_family"])
            if payload.get("candidate_family") is not None
            else None
        ),
        pv_preservation_dates=tuple(
            date.fromisoformat(str(item))
            for item in payload.get("pv_preservation_dates", ())
        ),
    )


def _serialize_daily(assignment: DailyChargeAssignment) -> dict[str, Any]:
    record = asdict(assignment)
    for key, value in record.items():
        if isinstance(value, (date, datetime)):
            record[key] = value.isoformat()
    record["main_segments"] = [
        {"segment_id": s.segment_id, "starts_at": s.starts_at.isoformat(),
         "ends_at": s.ends_at.isoformat()} for s in assignment.main_segments
    ]
    return record


def _deserialize_daily(item: dict[str, Any]) -> DailyChargeAssignment:
    return DailyChargeAssignment(
        execution_scope_id=item["execution_scope_id"],
        delivery_date=date.fromisoformat(item["delivery_date"]),
        timezone=item["timezone"], created_at=datetime.fromisoformat(item["created_at"]),
        route_plan_id=item.get("route_plan_id"),
        main_segments=tuple(DailyChargeSegment(
            segment_id=s["segment_id"], starts_at=datetime.fromisoformat(s["starts_at"]),
            ends_at=datetime.fromisoformat(s["ends_at"])
        ) for s in item.get("main_segments", ())),
        revision=item.get("revision", 0),
        revised_at=datetime.fromisoformat(item["revised_at"]) if item.get("revised_at") else None,
        revision_reason=(DailyChargeRevisionReason(item["revision_reason"])
                         if item.get("revision_reason") else None),
        revision_evidence_id=item.get("revision_evidence_id"),
        completed_at=datetime.fromisoformat(item["completed_at"])
                     if item.get("completed_at") else None,
        completion_evidence_id=item.get("completion_evidence_id"),
        completion_segment_id=item.get("completion_segment_id"),
    )
