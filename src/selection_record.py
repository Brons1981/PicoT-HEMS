"""Minimal SelectionRecord contract for PicoT HEMS.

Selection evaluates and proposes. It never creates, replaces, or activates a
persistent capability mapping. The mapping store is the only component allowed
to perform that transition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

_SCHEMA = "picot_hems.capability.selection_record"
_SCHEMA_VERSION = "1.0.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _source(candidate: dict[str, Any]) -> dict[str, Any]:
    entity_id = candidate.get("entity_id")
    return {
        "source_type": "HOME_ASSISTANT_ENTITY",
        "source_id": f"ha_entity:{entity_id}" if entity_id else None,
        "entity_id": entity_id,
        "integration": candidate.get("integration"),
        "platform": candidate.get("platform"),
        "device_id": candidate.get("device_id"),
        "config_entry_id": candidate.get("config_entry_id"),
        "native_identifier": candidate.get("native_identifier"),
    }


def _candidate_record(
    candidate: dict[str, Any],
    *,
    candidate_id: str,
    rank: int | None,
) -> dict[str, Any]:
    status = candidate.get("selection_status")
    semantic = candidate.get("semantic_validation") or {}
    return {
        "candidate_id": candidate_id,
        "source": _source(candidate),
        "eligibility": {
            "eligible": bool(candidate.get("eligible")),
            "rules": [
                {
                    "rule_id": "SEL-ELIG-001",
                    "result": "PASS" if candidate.get("eligible") else "FAIL",
                    "reasons": list(candidate.get("eligibility_reasons") or []),
                }
            ],
        },
        "semantic_validation": {
            "status": str(semantic.get("status") or "missing").upper(),
            "reasons": list(semantic.get("reasons") or []),
        },
        "ranking": {
            "rank": rank,
            "rules": list(candidate.get("selection_reasons") or []),
        },
        "selection_outcome": {
            "status": {
                "SELECTED": "PROPOSED",
                "NOT_SELECTED": "NOT_SELECTED",
                "INELIGIBLE": "INELIGIBLE",
            }.get(status, "NOT_SELECTED"),
            "reasons": list(candidate.get("selection_reasons") or []),
        },
    }


def build_selection_record(
    selection: dict[str, Any],
    *,
    capability_role: str = "primary",
    current_mapping: dict[str, Any] | None = None,
    selection_type: str = "INITIAL",
    trigger: str = "SYSTEM_SETUP",
    requested_by: str = "SYSTEM",
    now: Callable[[], str] = _utc_now,
    id_factory: Callable[[str], str] = _new_id,
) -> dict[str, Any]:
    """Build an auditable selection record from one capability selection result.

    Existing mappings are never silently replaced. An ACTIVE or
    TEMPORARILY_UNAVAILABLE mapping is retained. An INVALID mapping can produce
    a replacement proposal, but user confirmation remains mandatory.
    """
    created_at = now()
    audit_candidates = list(selection.get("candidate_audit") or [])
    eligible = [candidate for candidate in audit_candidates if candidate.get("eligible")]
    ranked = sorted(
        eligible,
        key=lambda item: (
            0 if item.get("selection_status") == "SELECTED" else 1,
            str(item.get("entity_id") or ""),
        ),
    )
    rank_by_entity = {
        item.get("entity_id"): index
        for index, item in enumerate(ranked, start=1)
    }

    candidate_records: list[dict[str, Any]] = []
    candidate_id_by_entity: dict[str, str] = {}
    for candidate in audit_candidates:
        candidate_id = id_factory("cand")
        entity_id = str(candidate.get("entity_id") or "")
        candidate_id_by_entity[entity_id] = candidate_id
        candidate_records.append(
            _candidate_record(
                candidate,
                candidate_id=candidate_id,
                rank=rank_by_entity.get(candidate.get("entity_id")),
            )
        )

    selected = selection.get("selected") or None
    selected_entity_id = str((selected or {}).get("entity_id") or "")
    selected_candidate_id = candidate_id_by_entity.get(selected_entity_id)
    mapping_status = str((current_mapping or {}).get("status") or "").upper()
    existing_mapping_present = current_mapping is not None

    if existing_mapping_present and mapping_status != "INVALID":
        proposal_status = "BLOCKED"
        proposed_action = "KEEP_EXISTING_MAPPING"
        activation_policy = "AUTO_BLOCKED"
        proposal_reasons = ["existing_mapping_preserved"]
        if mapping_status == "TEMPORARILY_UNAVAILABLE":
            proposal_reasons.append("temporary_unavailability_is_not_invalidity")
        decision = {
            "status": "APPROVED",
            "decision_type": "KEEP_EXISTING_MAPPING",
            "selected_candidate_id": None,
            "decided_at": created_at,
            "decided_by": "SYSTEM",
            "decision_reasons": proposal_reasons,
            "mapping_creation_requested": False,
            "created_mapping_id": None,
        }
        confirmation = {
            "required": False,
            "status": "NOT_REQUIRED",
            "requested_at": None,
            "resolved_at": None,
            "resolved_by": None,
            "selected_candidate_id": None,
            "user_reason": None,
        }
    elif selected is None:
        proposal_status = (
            "NO_ELIGIBLE_CANDIDATE" if audit_candidates else "NO_CANDIDATE"
        )
        proposed_action = "NO_ACTION"
        activation_policy = "AUTO_BLOCKED"
        proposal_reasons = [proposal_status.lower()]
        decision = {
            "status": "NO_SELECTION",
            "decision_type": "NO_VALID_SELECTION",
            "selected_candidate_id": None,
            "decided_at": created_at,
            "decided_by": "SYSTEM",
            "decision_reasons": proposal_reasons,
            "mapping_creation_requested": False,
            "created_mapping_id": None,
        }
        confirmation = {
            "required": False,
            "status": "NOT_REQUIRED",
            "requested_at": None,
            "resolved_at": None,
            "resolved_by": None,
            "selected_candidate_id": None,
            "user_reason": None,
        }
    else:
        replacement = existing_mapping_present and mapping_status == "INVALID"
        multiple_eligible = len(eligible) > 1
        confirmation_required = replacement or multiple_eligible
        proposal_status = "AMBIGUOUS" if multiple_eligible else "PROPOSED"
        proposed_action = "REPLACE_MAPPING" if replacement else "CREATE_MAPPING"
        activation_policy = (
            "USER_CONFIRMATION_REQUIRED" if confirmation_required else "AUTO_ALLOWED"
        )
        proposal_reasons = list(selected.get("selection_basis") or [])
        proposal_reasons.append(
            "existing_mapping_invalid" if replacement else "no_existing_mapping"
        )
        if multiple_eligible:
            proposal_reasons.append("multiple_eligible_candidates")

        confirmation = {
            "required": confirmation_required,
            "status": "PENDING" if confirmation_required else "NOT_REQUIRED",
            "requested_at": created_at if confirmation_required else None,
            "resolved_at": None,
            "resolved_by": None,
            "selected_candidate_id": None,
            "user_reason": None,
        }
        decision = {
            "status": "PENDING" if confirmation_required else "APPROVED",
            "decision_type": (
                None if confirmation_required else "AUTOMATIC_INITIAL_SELECTION"
            ),
            "selected_candidate_id": (
                None if confirmation_required else selected_candidate_id
            ),
            "decided_at": None if confirmation_required else created_at,
            "decided_by": None if confirmation_required else "SYSTEM",
            "decision_reasons": (
                [] if confirmation_required else ["automatic_initial_selection_allowed"]
            ),
            "mapping_creation_requested": not confirmation_required,
            "created_mapping_id": None,
        }

    return {
        "selection_record_id": id_factory("sel"),
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "capability_id": selection["capability_id"],
        "capability_role": capability_role,
        "selection_context": {
            "selection_type": selection_type,
            "trigger": trigger,
            "trigger_reference": None,
            "started_at": created_at,
            "requested_by": requested_by,
            "existing_mapping_present": existing_mapping_present,
        },
        "current_mapping": current_mapping,
        "candidates": candidate_records,
        "proposal": {
            "status": proposal_status,
            "candidate_id": selected_candidate_id,
            "source_id": (
                f"ha_entity:{selected_entity_id}" if selected_entity_id else None
            ),
            "proposed_action": proposed_action,
            "activation_policy": activation_policy,
            "proposal_reasons": proposal_reasons,
            "created_at": created_at,
        },
        "confirmation": confirmation,
        "decision": decision,
        "audit": {
            "selection_engine_version": "0.1.0",
            "rule_set_version": "1.0.0",
            "created_at": created_at,
            "completed_at": None if decision["status"] == "PENDING" else created_at,
            "immutable": decision["status"] != "PENDING",
        },
    }
