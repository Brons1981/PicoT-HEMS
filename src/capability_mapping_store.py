"""Persistent-contract core for PicoT HEMS capability mappings.

The mapping store is the only component allowed to activate or replace a
capability source. This first implementation is deliberately storage-agnostic
and keeps records in memory; its records are plain dictionaries so a JSON/file
or database adapter can be added without changing the contract.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

_SCHEMA = "picot_hems.capability.mapping"
_SCHEMA_VERSION = "1.0.0"
_ACTIVE_STATES = {"ACTIVE", "TEMPORARILY_UNAVAILABLE"}


class MappingStoreError(ValueError):
    """Raised when a mapping-store invariant would be violated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _key(capability_id: str, capability_role: str) -> tuple[str, str]:
    if not capability_id:
        raise MappingStoreError("capability_id is required")
    if not capability_role:
        raise MappingStoreError("capability_role is required")
    return capability_id, capability_role


def _selected_candidate(selection_record: dict[str, Any]) -> dict[str, Any]:
    decision = selection_record.get("decision") or {}
    candidate_id = decision.get("selected_candidate_id")
    if not candidate_id:
        raise MappingStoreError("selection decision has no selected candidate")

    for candidate in selection_record.get("candidates") or []:
        if candidate.get("candidate_id") == candidate_id:
            if not (candidate.get("eligibility") or {}).get("eligible"):
                raise MappingStoreError("selected candidate is not eligible")
            semantic_status = str(
                (candidate.get("semantic_validation") or {}).get("status") or ""
            ).upper()
            if semantic_status != "VALID":
                raise MappingStoreError("selected candidate is not semantically valid")
            source = candidate.get("source") or {}
            if not source.get("source_id"):
                raise MappingStoreError("selected candidate has no source_id")
            return candidate

    raise MappingStoreError("selected candidate is missing from SelectionRecord")


class CapabilityMappingStore:
    """Manage active capability mappings and immutable historical versions."""

    def __init__(
        self,
        *,
        now: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self._now = now
        self._id_factory = id_factory
        self._records: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def activate_from_selection(
        self,
        selection_record: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or replace a mapping from an approved SelectionRecord.

        Initial activation is allowed only when no current mapping exists.
        Replacement is allowed only when the current mapping is INVALID and the
        SelectionRecord explicitly proposes REPLACE_MAPPING.
        """
        decision = selection_record.get("decision") or {}
        proposal = selection_record.get("proposal") or {}
        if decision.get("status") != "APPROVED":
            raise MappingStoreError("selection decision is not approved")
        if not decision.get("mapping_creation_requested"):
            raise MappingStoreError("selection did not request mapping creation")

        capability_id = str(selection_record.get("capability_id") or "")
        capability_role = str(selection_record.get("capability_role") or "")
        mapping_key = _key(capability_id, capability_role)
        history = self._records.setdefault(mapping_key, [])
        current = history[-1] if history else None
        action = proposal.get("proposed_action")

        if current is None:
            if action != "CREATE_MAPPING":
                raise MappingStoreError("initial activation requires CREATE_MAPPING")
        else:
            if current["status"] in _ACTIVE_STATES:
                raise MappingStoreError("active mapping cannot be silently replaced")
            if current["status"] != "INVALID":
                raise MappingStoreError("only an INVALID mapping can be replaced")
            if action != "REPLACE_MAPPING":
                raise MappingStoreError("replacement requires REPLACE_MAPPING")

        candidate = _selected_candidate(selection_record)
        source = deepcopy(candidate["source"])
        activated_at = self._now()
        mapping_id = current["mapping_id"] if current else self._id_factory("map")
        version = (current["mapping_version"] + 1) if current else 1

        record = {
            "mapping_id": mapping_id,
            "schema": _SCHEMA,
            "schema_version": _SCHEMA_VERSION,
            "mapping_version": version,
            "capability_id": capability_id,
            "capability_role": capability_role,
            "status": "ACTIVE",
            "source": source,
            "selection_record_id": selection_record.get("selection_record_id"),
            "selected_candidate_id": candidate.get("candidate_id"),
            "replaces_mapping_version": current["mapping_version"] if current else None,
            "activated_at": activated_at,
            "status_changed_at": activated_at,
            "invalidated_at": None,
            "invalidity_reason": None,
            "history_immutable": True,
        }
        history.append(record)
        return deepcopy(record)

    def get_current(
        self,
        capability_id: str,
        capability_role: str = "primary",
    ) -> dict[str, Any] | None:
        history = self._records.get(_key(capability_id, capability_role), [])
        return deepcopy(history[-1]) if history else None

    def get_active(
        self,
        capability_id: str,
        capability_role: str = "primary",
    ) -> dict[str, Any] | None:
        current = self.get_current(capability_id, capability_role)
        if current and current["status"] in _ACTIVE_STATES:
            return current
        return None

    def get_history(
        self,
        capability_id: str,
        capability_role: str = "primary",
    ) -> list[dict[str, Any]]:
        return deepcopy(self._records.get(_key(capability_id, capability_role), []))

    def mark_temporarily_unavailable(
        self,
        capability_id: str,
        capability_role: str = "primary",
    ) -> dict[str, Any]:
        current = self._require_current(capability_id, capability_role)
        if current["status"] == "TEMPORARILY_UNAVAILABLE":
            return deepcopy(current)
        if current["status"] != "ACTIVE":
            raise MappingStoreError("only an ACTIVE mapping can become temporarily unavailable")
        return self._append_status_version(current, "TEMPORARILY_UNAVAILABLE")

    def restore_available(
        self,
        capability_id: str,
        capability_role: str = "primary",
    ) -> dict[str, Any]:
        current = self._require_current(capability_id, capability_role)
        if current["status"] == "ACTIVE":
            return deepcopy(current)
        if current["status"] != "TEMPORARILY_UNAVAILABLE":
            raise MappingStoreError("only a temporarily unavailable mapping can be restored")
        return self._append_status_version(current, "ACTIVE")

    def invalidate(
        self,
        capability_id: str,
        reason: str,
        capability_role: str = "primary",
    ) -> dict[str, Any]:
        if not reason:
            raise MappingStoreError("objective invalidity reason is required")
        current = self._require_current(capability_id, capability_role)
        if current["status"] == "INVALID":
            return deepcopy(current)
        if current["status"] not in _ACTIVE_STATES:
            raise MappingStoreError("mapping cannot be invalidated from its current state")
        return self._append_status_version(current, "INVALID", reason=reason)

    def _require_current(self, capability_id: str, capability_role: str) -> dict[str, Any]:
        mapping_key = _key(capability_id, capability_role)
        history = self._records.get(mapping_key, [])
        if not history:
            raise MappingStoreError("mapping does not exist")
        return history[-1]

    def _append_status_version(
        self,
        current: dict[str, Any],
        status: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        changed_at = self._now()
        record = deepcopy(current)
        record["mapping_version"] = current["mapping_version"] + 1
        record["status"] = status
        record["status_changed_at"] = changed_at
        record["replaces_mapping_version"] = current["mapping_version"]
        if status == "INVALID":
            record["invalidated_at"] = changed_at
            record["invalidity_reason"] = reason
        elif status == "ACTIVE":
            record["invalidated_at"] = None
            record["invalidity_reason"] = None
        self._records[(current["capability_id"], current["capability_role"])].append(record)
        return deepcopy(record)
