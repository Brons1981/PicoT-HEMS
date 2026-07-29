"""Deterministic lifecycle engine for PicoT HEMS capability mappings.

The lifecycle engine interprets factual mapping events and delegates valid state
changes to the Capability Mapping Store. It never discovers, selects, activates,
or replaces a source by itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from capability_mapping_store import CapabilityMappingStore, MappingStoreError

_SCHEMA = "picot_hems.capability.lifecycle_event"
_SCHEMA_VERSION = "1.0.0"
_ENGINE_VERSION = "0.1.1"

_TEMPORARY_EVENTS = {"SOURCE_UNAVAILABLE"}
_RESTORE_EVENTS = {"SOURCE_AVAILABLE"}
_OBJECTIVE_INVALIDITY_EVENTS = {
    "ENTITY_REMOVED": "entity_removed",
    "DEVICE_REMOVED": "device_removed",
    "CONFIG_ENTRY_REMOVED": "config_entry_removed",
    "SEMANTIC_INVALID": "semantic_invalid",
    "SOURCE_IDENTIFIER_CHANGED": "source_identifier_changed",
}
_SUPPORTED_EVENTS = (
    _TEMPORARY_EVENTS | _RESTORE_EVENTS | set(_OBJECTIVE_INVALIDITY_EVENTS)
)


class LifecycleError(ValueError):
    """Raised when a lifecycle event is unsupported or cannot be applied."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class CapabilityLifecycleEngine:
    """Apply deterministic lifecycle transitions to capability mappings."""

    def __init__(
        self,
        mapping_store: CapabilityMappingStore,
        *,
        now: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self._mapping_store = mapping_store
        self._now = now
        self._id_factory = id_factory
        self._records: list[dict[str, Any]] = []

    def process_event(
        self,
        *,
        capability_id: str,
        event_type: str,
        capability_role: str = "primary",
        observed_by: str = "SYSTEM",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process one factual lifecycle event and return its immutable record."""
        normalized_event = str(event_type or "").upper()
        if normalized_event not in _SUPPORTED_EVENTS:
            raise LifecycleError(f"unsupported lifecycle event: {normalized_event or '<empty>'}")
        if not capability_id:
            raise LifecycleError("capability_id is required")
        if not capability_role:
            raise LifecycleError("capability_role is required")

        occurred_at = self._now()
        before = self._mapping_store.get_current(capability_id, capability_role)
        if before is None:
            raise LifecycleError("mapping does not exist")

        try:
            if normalized_event in _TEMPORARY_EVENTS:
                after = self._mapping_store.mark_temporarily_unavailable(
                    capability_id, capability_role
                )
                action = "MARK_TEMPORARILY_UNAVAILABLE"
                rediscovery_required = False
                reason = "temporary_unavailability_is_not_invalidity"
            elif normalized_event in _RESTORE_EVENTS:
                if before["status"] != "TEMPORARILY_UNAVAILABLE":
                    raise LifecycleError(
                        "SOURCE_AVAILABLE is valid only when the mapping is temporarily unavailable"
                    )
                after = self._mapping_store.restore_available(
                    capability_id, capability_role
                )
                action = "RESTORE_ACTIVE"
                rediscovery_required = False
                reason = "source_available_again"
            else:
                invalidity_reason = _OBJECTIVE_INVALIDITY_EVENTS[normalized_event]
                after = self._mapping_store.invalidate(
                    capability_id,
                    invalidity_reason,
                    capability_role,
                )
                action = "INVALIDATE_MAPPING"
                rediscovery_required = True
                reason = invalidity_reason
        except MappingStoreError as exc:
            raise LifecycleError(str(exc)) from exc

        changed = after["mapping_version"] != before["mapping_version"]
        record = {
            "lifecycle_event_id": self._id_factory("life"),
            "schema": _SCHEMA,
            "schema_version": _SCHEMA_VERSION,
            "engine_version": _ENGINE_VERSION,
            "capability_id": capability_id,
            "capability_role": capability_role,
            "event_type": normalized_event,
            "observed_by": observed_by,
            "occurred_at": occurred_at,
            "evidence": dict(evidence or {}),
            "transition": {
                "mapping_id": before["mapping_id"],
                "from_mapping_version": before["mapping_version"],
                "to_mapping_version": after["mapping_version"],
                "from_status": before["status"],
                "to_status": after["status"],
                "changed": changed,
                "action": action,
                "reason": reason,
            },
            "rediscovery": {
                "required": rediscovery_required,
                "scope": (
                    {
                        "capability_id": capability_id,
                        "capability_role": capability_role,
                    }
                    if rediscovery_required
                    else None
                ),
            },
            "selection_required": rediscovery_required,
            "source_replacement_performed": False,
            "immutable": True,
        }
        self._records.append(record)
        return _deepcopy_record(record)

    def get_records(
        self,
        *,
        capability_id: str | None = None,
        capability_role: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return immutable copies of lifecycle records, optionally filtered."""
        records = self._records
        if capability_id is not None:
            records = [r for r in records if r["capability_id"] == capability_id]
        if capability_role is not None:
            records = [r for r in records if r["capability_role"] == capability_role]
        return [_deepcopy_record(record) for record in records]


def _deepcopy_record(record: dict[str, Any]) -> dict[str, Any]:
    # Local import keeps this module's public surface small.
    from copy import deepcopy

    return deepcopy(record)
