"""Durable active execution commitment state required by V2ADR-052."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

COMMITMENT_METHOD_VERSION = "household-energy-path-commitment:v2"
LEGACY_COMMITMENT_METHOD_VERSION = "legacy-pre-household-simulation"


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

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.execution_scope_id,
                self.plan_id,
                self.primitive,
                self.source_policy,
                self.selection_method_version,
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
        payload["commitments"][commitment.execution_scope_id] = serialized
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
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported commitment schema")
            if not isinstance(payload.get("commitments"), dict):
                raise ValueError("commitments must be an object")
            return cast(dict[str, Any], payload)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            self._record_incident("commitment_store_reset_before_write", exc)
            return {"schema_version": 1, "commitments": {}}

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
    )
