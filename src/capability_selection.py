"""Deterministic capability selection for PicoT HEMS.

Step 2.7 selects at most one entity for each stable capability ID. Selection
uses a fixed rule hierarchy; it does not use probabilities, learned weights or
opaque scoring.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


_INVALID_STATES = {"", "none", "null", "unknown", "unavailable"}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _eligibility(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether a candidate may be selected and the factual reasons."""
    reasons: list[str] = []
    entity_id = _normalized(candidate.get("entity_id"))
    state = _normalized(candidate.get("state"))

    if not entity_id or "." not in entity_id:
        reasons.append("invalid_entity_id")
    if state in _INVALID_STATES:
        reasons.append(f"state_not_usable:{state or 'empty'}")

    return not reasons, reasons


def _selection_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Return a stable priority key based on the documented rule hierarchy.

    Lower tuples have priority. The entity_id is only the final deterministic
    tie-breaker and carries no semantic preference.
    """
    return (
        0 if candidate.get("device_id") else 1,
        0 if candidate.get("config_entry_id") else 1,
        0 if candidate.get("platform") else 1,
        -len(candidate.get("reasons") or []),
        _normalized(candidate.get("entity_id")),
    )


def _selection_basis(candidate: dict[str, Any]) -> list[str]:
    basis = ["usable_current_state"]
    if candidate.get("device_id"):
        basis.append("linked_device")
    if candidate.get("config_entry_id"):
        basis.append("linked_config_entry")
    if candidate.get("platform"):
        basis.append("known_platform")
    basis.append(f"discovery_evidence_count:{len(candidate.get('reasons') or [])}")
    basis.append("stable_entity_id_tiebreaker")
    return basis


def select_capabilities(discovery_result: dict[str, Any]) -> dict[str, Any]:
    """Select at most one candidate for every discovered capability.

    Every candidate remains present in the audit output. Non-selected records
    state whether they were ineligible or lost to a higher-priority candidate.
    """
    mappings: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for capability in discovery_result.get("capabilities", []):
        candidates = capability.get("candidates") or []
        evaluated: list[dict[str, Any]] = []
        eligible: list[dict[str, Any]] = []

        for candidate in candidates:
            is_eligible, reasons = _eligibility(candidate)
            record = dict(candidate)
            record["eligible"] = is_eligible
            record["eligibility_reasons"] = reasons
            evaluated.append(record)
            if is_eligible:
                eligible.append(record)

        selected = min(eligible, key=_selection_key) if eligible else None
        selected_entity_id = selected.get("entity_id") if selected else None

        for record in evaluated:
            if not record["eligible"]:
                record["selection_status"] = "INELIGIBLE"
                record["selection_reasons"] = record["eligibility_reasons"]
            elif record.get("entity_id") == selected_entity_id:
                record["selection_status"] = "SELECTED"
                record["selection_reasons"] = _selection_basis(record)
            else:
                record["selection_status"] = "NOT_SELECTED"
                record["selection_reasons"] = [
                    f"higher_priority_candidate:{selected_entity_id}"
                ]

        if selected:
            status = "SELECTED"
            selected_record = {
                "entity_id": selected["entity_id"],
                "domain": selected.get("domain"),
                "device_id": selected.get("device_id"),
                "config_entry_id": selected.get("config_entry_id"),
                "platform": selected.get("platform"),
                "selection_basis": _selection_basis(selected),
            }
        elif candidates:
            status = "NO_USABLE_CANDIDATE"
            selected_record = None
        else:
            status = "NO_CANDIDATE"
            selected_record = None

        status_counts[status] += 1
        mappings.append(
            {
                "capability_id": capability["id"],
                "category": capability.get("category"),
                "kind": capability.get("kind"),
                "status": status,
                "selected": selected_record,
                "candidate_count": len(candidates),
                "eligible_candidate_count": len(eligible),
                "candidate_audit": evaluated,
            }
        )

    selected_count = status_counts["SELECTED"]
    return {
        "metadata": {
            "schema": "picot_hems.capability.selection",
            "schema_version": "0.1.0",
            "method": "fixed_priority_rules",
            "probabilistic_selection": False,
            "learning_used": False,
            "maximum_selected_per_capability": 1,
            "rule_order": [
                "usable_current_state_required",
                "prefer_linked_device",
                "prefer_linked_config_entry",
                "prefer_known_platform",
                "prefer_more_discovery_evidence",
                "entity_id_lexical_tiebreaker",
            ],
        },
        "summary": {
            "capability_count": len(mappings),
            "selected_capability_count": selected_count,
            "unselected_capability_count": len(mappings) - selected_count,
            "status_counts": dict(sorted(status_counts.items())),
        },
        "mappings": mappings,
    }
