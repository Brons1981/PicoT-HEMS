"""Auditable end-to-end validation reporting for capability selection.

This module does not discover, validate, select, activate, or replace mappings.
It only converts an existing deterministic selection result into a reviewable
report and optionally compares the proposal with a manually approved truth set.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any, Mapping


_EXPECTATION_STATUSES = {
    "MATCH",
    "MISMATCH",
    "EXPECTED_NONE_MATCH",
    "EXPECTED_NONE_MISMATCH",
    "NOT_REVIEWED",
}


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    semantic = candidate.get("semantic_validation") or {}
    return {
        "entity_id": candidate.get("entity_id"),
        "state": candidate.get("state"),
        "unit_of_measurement": candidate.get("unit_of_measurement"),
        "device_class": candidate.get("device_class"),
        "platform": candidate.get("platform"),
        "eligible": bool(candidate.get("eligible")),
        "eligibility_reasons": list(candidate.get("eligibility_reasons") or []),
        "semantic_status": str(semantic.get("status") or "MISSING").upper(),
        "semantic_reasons": list(semantic.get("reasons") or []),
        "selection_status": candidate.get("selection_status"),
        "selection_reasons": list(candidate.get("selection_reasons") or []),
    }


def _expectation_status(
    capability_id: str,
    selected_entity_id: str | None,
    expected_mappings: Mapping[str, str | None] | None,
) -> tuple[str, str | None]:
    if expected_mappings is None or capability_id not in expected_mappings:
        return "NOT_REVIEWED", None

    expected = expected_mappings[capability_id]
    if expected is None:
        return (
            "EXPECTED_NONE_MATCH" if selected_entity_id is None else "EXPECTED_NONE_MISMATCH",
            None,
        )
    return ("MATCH" if selected_entity_id == expected else "MISMATCH", expected)


def build_selection_validation_report(
    selection_result: Mapping[str, Any],
    *,
    expected_mappings: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Build a deterministic report grouped by capability category.

    ``expected_mappings`` is the manually approved truth set. A value of ``None``
    explicitly means that no entity should be selected for that capability.
    Missing keys remain ``NOT_REVIEWED`` and are never treated as correct.
    """
    rows: list[dict[str, Any]] = []
    expectation_counts: Counter[str] = Counter()
    selection_counts: Counter[str] = Counter()

    for mapping in selection_result.get("mappings") or []:
        capability_id = str(mapping.get("capability_id") or "")
        selected = mapping.get("selected") or None
        selected_entity_id = selected.get("entity_id") if selected else None
        expectation_status, expected_entity_id = _expectation_status(
            capability_id, selected_entity_id, expected_mappings
        )
        if expectation_status not in _EXPECTATION_STATUSES:
            raise ValueError(f"unsupported expectation status: {expectation_status}")

        row = {
            "capability_id": capability_id,
            "category": mapping.get("category") or "uncategorized",
            "kind": mapping.get("kind"),
            "selection_status": mapping.get("status"),
            "selected_entity_id": selected_entity_id,
            "selection_basis": list((selected or {}).get("selection_basis") or []),
            "candidate_count": int(mapping.get("candidate_count") or 0),
            "eligible_candidate_count": int(mapping.get("eligible_candidate_count") or 0),
            "expected_entity_id": expected_entity_id,
            "expectation_status": expectation_status,
            "candidates": [
                _candidate_summary(candidate)
                for candidate in mapping.get("candidate_audit") or []
            ],
        }
        rows.append(row)
        selection_counts[str(row["selection_status"] or "UNKNOWN")] += 1
        expectation_counts[expectation_status] += 1

    rows.sort(key=lambda row: (str(row["category"]), str(row["capability_id"])))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["category"])].append(deepcopy(row))

    reviewed_count = len(rows) - expectation_counts["NOT_REVIEWED"]
    failed_review_count = (
        expectation_counts["MISMATCH"] + expectation_counts["EXPECTED_NONE_MISMATCH"]
    )

    return {
        "metadata": {
            "schema": "picot_hems.capability.selection_validation_report",
            "schema_version": "1.0.0",
            "source_schema": (selection_result.get("metadata") or {}).get("schema"),
            "read_only": True,
            "selection_performed": False,
            "mapping_activation_performed": False,
        },
        "summary": {
            "capability_count": len(rows),
            "reviewed_capability_count": reviewed_count,
            "unreviewed_capability_count": expectation_counts["NOT_REVIEWED"],
            "failed_review_count": failed_review_count,
            "review_passed": reviewed_count > 0 and failed_review_count == 0,
            "selection_status_counts": dict(sorted(selection_counts.items())),
            "expectation_status_counts": dict(sorted(expectation_counts.items())),
        },
        "categories": [
            {
                "category": category,
                "capability_count": len(category_rows),
                "results": category_rows,
            }
            for category, category_rows in sorted(grouped.items())
        ],
        "results": deepcopy(rows),
    }


def render_selection_validation_markdown(report: Mapping[str, Any]) -> str:
    """Render the report as a compact human-reviewable Markdown table."""
    lines = [
        "# PicoT capability selection validation",
        "",
        "| Soort | Capability | Status | Gekozen entiteit | Verwacht | Controle |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("results") or []:
        lines.append(
            "| {category} | `{capability}` | {status} | `{selected}` | `{expected}` | {check} |".format(
                category=row.get("category") or "-",
                capability=row.get("capability_id") or "-",
                status=row.get("selection_status") or "-",
                selected=row.get("selected_entity_id") or "—",
                expected=(
                    row.get("expected_entity_id")
                    if row.get("expectation_status") != "NOT_REVIEWED"
                    else "niet beoordeeld"
                ) or "—",
                check=row.get("expectation_status") or "-",
            )
        )

    lines.extend(["", "## Kandidaten per capability", ""])
    for row in report.get("results") or []:
        lines.append(f"### `{row.get('capability_id')}`")
        candidates = row.get("candidates") or []
        if not candidates:
            lines.append("Geen kandidaten gevonden.")
            lines.append("")
            continue
        for candidate in candidates:
            reasons = (
                candidate.get("selection_reasons")
                or candidate.get("eligibility_reasons")
                or candidate.get("semantic_reasons")
                or []
            )
            reason_text = ", ".join(str(reason) for reason in reasons) or "geen reden vastgelegd"
            lines.append(
                "- `{entity}` — {selection}; semantic={semantic}; eligible={eligible}; {reasons}".format(
                    entity=candidate.get("entity_id") or "—",
                    selection=candidate.get("selection_status") or "—",
                    semantic=candidate.get("semantic_status") or "—",
                    eligible=str(bool(candidate.get("eligible"))).lower(),
                    reasons=reason_text,
                )
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
