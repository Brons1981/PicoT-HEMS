"""Durable observer-only storage-mode provenance for the live runtime."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from picot.v2.planning_input import PlanningInputBundle
from picot.v2.storage_mode_provenance import (
    StorageModeControlProvenance,
    initial_storage_mode_provenance,
    observe_storage_mode,
    record_planner_mode_application,
    reset_storage_mode_override,
)

SCHEMA_VERSION = 1
_VALID_STATUSES = {
    "unverified",
    "planner_owned",
    "manual_override",
    "released",
}


class InvalidStorageModeProvenanceError(ValueError):
    """Persisted provenance cannot be trusted."""


class StorageModeProvenanceStore:
    """Persist one versioned provenance document with atomic replacement."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> StorageModeControlProvenance | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise InvalidStorageModeProvenanceError(
                    "persisted provenance root must be an object"
                )
            if payload.get("schema_version") != SCHEMA_VERSION:
                raise InvalidStorageModeProvenanceError(
                    "persisted provenance schema is unsupported"
                )
            raw = payload.get("provenance")
            if not isinstance(raw, dict):
                raise InvalidStorageModeProvenanceError(
                    "persisted provenance payload must be an object"
                )
            return _deserialize_provenance(raw)
        except (
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, InvalidStorageModeProvenanceError):
                raise
            raise InvalidStorageModeProvenanceError(
                "persisted provenance is invalid"
            ) from exc

    def save(self, provenance: StorageModeControlProvenance) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "provenance": _serialize_provenance(provenance),
        }
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()


class LiveStorageModeProvenanceRuntime:
    """Restore, transition, and durably commit live provenance state."""

    def __init__(self, store: StorageModeProvenanceStore) -> None:
        self._store = store
        self._current: StorageModeControlProvenance | None = None
        self._load_attempted = False
        self._persisted_state_invalid = False

    def observe_vendor_mode(
        self,
        vendor_mode: str,
        *,
        observed_at: datetime,
    ) -> StorageModeControlProvenance:
        current = self._load_current()
        if current is None:
            current = initial_storage_mode_provenance(
                observed_vendor_mode=vendor_mode,
                observed_at=observed_at,
            )
            if self._persisted_state_invalid:
                current = replace(
                    current,
                    transition_reason="persisted_provenance_invalid",
                )
        else:
            current = observe_storage_mode(
                current,
                observed_vendor_mode=vendor_mode,
                observed_at=observed_at,
            )
        self._commit(current)
        return current

    def record_planner_application(
        self,
        vendor_mode: str,
        *,
        applied_at: datetime,
        application_id: str,
    ) -> StorageModeControlProvenance:
        current = self._require_current()
        updated = record_planner_mode_application(
            current,
            vendor_mode=vendor_mode,
            applied_at=applied_at,
            application_id=application_id,
        )
        self._commit(updated)
        return updated

    def reset_manual_override(
        self,
        *,
        observed_vendor_mode: str,
        reset_at: datetime,
        reset_id: str,
    ) -> StorageModeControlProvenance:
        current = self._require_current()
        if not current.manual_override_active:
            raise ValueError("no manual override is active")
        updated = reset_storage_mode_override(
            current,
            observed_vendor_mode=observed_vendor_mode,
            reset_at=reset_at,
            reset_id=reset_id,
        )
        self._commit(updated)
        return updated

    def reset_current_manual_override(
        self,
        *,
        reset_at: datetime,
        reset_id: str,
    ) -> StorageModeControlProvenance:
        current = self._require_current()
        return self.reset_manual_override(
            observed_vendor_mode=current.observed_vendor_mode,
            reset_at=reset_at,
            reset_id=reset_id,
        )

    def _load_current(self) -> StorageModeControlProvenance | None:
        if self._load_attempted:
            return self._current
        self._load_attempted = True
        try:
            self._current = self._store.load()
        except InvalidStorageModeProvenanceError:
            self._persisted_state_invalid = True
            self._current = None
        return self._current

    def _require_current(self) -> StorageModeControlProvenance:
        current = self._load_current()
        if current is None:
            raise ValueError("a vendor-mode observation is required first")
        return current

    def _commit(self, provenance: StorageModeControlProvenance) -> None:
        self._store.save(provenance)
        self._current = provenance


def attach_storage_mode_provenance(
    bundle: PlanningInputBundle,
    runtime: LiveStorageModeProvenanceRuntime,
) -> PlanningInputBundle:
    """Attach restored provenance to a live immutable input bundle."""
    evidence = bundle.snapshot.storage_mode_capability_evidence
    if evidence is None or evidence.current_vendor_mode is None:
        return bundle
    provenance = runtime.observe_vendor_mode(
        evidence.current_vendor_mode,
        observed_at=evidence.captured_at,
    )
    return replace(
        bundle,
        snapshot=replace(
            bundle.snapshot,
            storage_mode_control_provenance=provenance,
        ),
    )


def _serialize_provenance(
    provenance: StorageModeControlProvenance,
) -> dict[str, Any]:
    payload = asdict(provenance)
    payload["observed_at"] = provenance.observed_at.isoformat()
    return payload


def _deserialize_provenance(
    payload: dict[str, Any],
) -> StorageModeControlProvenance:
    required = {
        "status",
        "observed_vendor_mode",
        "observed_at",
        "last_planner_vendor_mode",
        "last_planner_application_id",
        "manual_override_active",
        "transition_reason",
        "reset_id",
    }
    if set(payload) != required:
        raise InvalidStorageModeProvenanceError(
            "persisted provenance fields are invalid"
        )
    status = payload["status"]
    if status not in _VALID_STATUSES:
        raise InvalidStorageModeProvenanceError(
            "persisted provenance status is invalid"
        )
    try:
        observed_at = datetime.fromisoformat(payload["observed_at"])
        return StorageModeControlProvenance(
            status=status,
            observed_vendor_mode=payload["observed_vendor_mode"],
            observed_at=observed_at,
            last_planner_vendor_mode=payload["last_planner_vendor_mode"],
            last_planner_application_id=(
                payload["last_planner_application_id"]
            ),
            manual_override_active=payload["manual_override_active"],
            transition_reason=payload["transition_reason"],
            reset_id=payload["reset_id"],
        )
    except (TypeError, ValueError) as exc:
        raise InvalidStorageModeProvenanceError(
            "persisted provenance values are invalid"
        ) from exc
