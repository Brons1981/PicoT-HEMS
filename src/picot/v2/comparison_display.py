"""Bound optional dashboard examples without changing canonical decisions."""
from __future__ import annotations

from typing import Any

DISPLAY_LIMIT = 50


def _examples(rows: list[Any], protected: set[object]) -> list[Any]:
    selected = {i for i, row in enumerate(rows) if isinstance(row, dict) and (
        row.get("candidate_id") in protected or row.get("selected") or row.get("incumbent"))}
    # Include an example of each variant and rejection state, then original order.
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        group = (row.get("variant"), bool(row.get("invalidity_reasons")
                                         or row.get("evaluation_invalidity_reasons")))
        if group not in seen:
            selected.add(i)
            seen.add(group)
    for i in range(len(rows)):
        if len(selected) >= DISPLAY_LIMIT:
            break
        selected.add(i)
    return [row for i, row in enumerate(rows) if i in selected]


def compact_dashboard_comparison(view: dict[str, Any]) -> dict[str, Any]:
    """Copy only display containers; never mutate caller or planner evidence."""
    planning = view.get("planning_status")
    if not isinstance(planning, dict):
        return view
    comparison = planning.get("market_revision_comparison")
    protected: set[object] = set()
    if isinstance(comparison, dict):
        protected.update((comparison.get("winning_candidate_id"),
                          comparison.get("incumbent_candidate_id")))
    protected.discard(None)
    result = dict(view)
    status = dict(planning)
    result["planning_status"] = status
    if isinstance(comparison, dict):
        rows = comparison.get("alternatives")
        if isinstance(rows, list) and len(rows) > DISPLAY_LIMIT:
            shown = _examples(rows, protected)
            dictionary = comparison.get("evidence_dictionary", {})
            references = {row.get("evidence_ids_ref") for row in shown}
            references.update(dictionary[r]["base"] for r in tuple(references)
                              if r in dictionary and "base" in dictionary[r])
            status["market_revision_comparison"] = {
                **comparison, "alternatives": shown,
                "alternative_count": len(rows), "omitted_alternative_count": len(rows)-len(shown),
                "display_selection": "selected_incumbent_and_examples",
                "evidence_dictionary": {k: v for k, v in dictionary.items() if k in references},
            }
    alternatives = status.get("alternatives")
    if isinstance(alternatives, list) and len(alternatives) > DISPLAY_LIMIT:
        status["alternatives"] = _examples(alternatives, protected)
        status["alternative_count"] = len(alternatives)
    explanation = view.get("plan_explanation")
    if isinstance(explanation, dict):
        plans = explanation.get("plans")
        if isinstance(plans, list) and len(plans) > DISPLAY_LIMIT:
            result["plan_explanation"] = {
                **explanation, "plans": _examples(plans, protected), "plan_count": len(plans),
            }
    return result
