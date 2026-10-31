"""Bounded display-only persistence of admitted plan-decision evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_CACHE_BYTES = 65_536
ADMITTED = {"retained", "replaced", "selected"}


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing assessment time")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("assessment time must be timezone-aware")
    return result


def _identities(value: object) -> set[tuple[str, str]] | None:
    if not isinstance(value, list) or not value:
        return None
    result = set()
    for row in value:
        if not isinstance(row, dict):
            return None
        plan_id, path_id = row.get("plan_id"), row.get("energy_path_id")
        if (not isinstance(plan_id, str) or not plan_id
                or not isinstance(path_id, str) or not path_id):
            return None
        result.add((plan_id, path_id))
    return result if len(result) == len(value) else None


def retain_plan_decision(
    current: dict[str, object], previous: dict[str, object],
) -> dict[str, object]:
    """Carry original evidence only across observations of the same admitted plans."""
    fresh = current.get("plan_decision")
    earlier = previous.get("plan_decision")
    decision = current.get("decision")
    if (not isinstance(fresh, dict) or fresh.get("source") != "observation"
            or fresh.get("status") != "retained"
            or not isinstance(decision, dict) or decision.get("status") != "plan_retained"
            or not isinstance(earlier, dict) or earlier.get("source") != "comparison"
            or earlier.get("status") not in ADMITTED):
        return current
    governed = _identities(earlier.get("execution_plans"))
    if governed is None or governed != _identities(current.get("execution_plans")):
        return current
    try:
        if _time(earlier.get("assessed_at")) > _time(current.get("captured_at")):
            return current
    except (ValueError, TypeError):
        return current
    carried = {**earlier, "evidence_retained": True}
    narrative = fresh.get("narrative")
    prior_narrative = earlier.get("narrative")
    if isinstance(narrative, dict):
        if (not narrative.get("energy_available") and isinstance(prior_narrative, dict)
                and prior_narrative.get("energy_available")):
            narrative = {**prior_narrative, "windows": narrative.get("windows", [])}
        carried["narrative"] = narrative
    return {**current, "plan_decision": carried}


def _validated(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported plan-decision cache")
    evidence = value.get("plan_decision")
    if (not isinstance(evidence, dict) or evidence.get("source") != "comparison"
            or evidence.get("status") not in ADMITTED
            or _identities(evidence.get("execution_plans")) is None
            or not isinstance(evidence.get("reason"), str) or not evidence["reason"].strip()):
        raise ValueError("incomplete admitted plan-decision evidence")
    _time(evidence.get("assessed_at"))
    # Reject nonfinite numbers anywhere, not only in currently displayed fields.
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CACHE_BYTES:
        raise ValueError("plan-decision cache exceeds bound")
    return dict(evidence)


class PlanDecisionCache:
    """Never feeds planning, evaluation, commitment or execution."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._evidence: dict[str, object] | None = None
        try:
            with path.open("rb") as source:
                raw = source.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                raise ValueError("plan-decision cache exceeds bound")
            self._evidence = _validated(json.loads(raw))
        except (OSError, ValueError, TypeError, RecursionError):
            pass

    def apply(self, current: dict[str, object]) -> dict[str, object]:
        evidence = current.get("plan_decision")
        decision = current.get("decision")
        if isinstance(evidence, dict) and evidence.get("source") == "comparison":
            try:
                saved = _validated({"schema_version": 1, "plan_decision": evidence})
                if (not isinstance(decision, dict)
                        or decision.get("status") not in {"winner_selected", "plan_retained"}
                        or _identities(saved.get("execution_plans")) !=
                        _identities(current.get("execution_plans"))
                        or _time(saved.get("assessed_at")) > _time(current.get("captured_at"))):
                    return current
                if saved != self._evidence:
                    encoded = json.dumps({"schema_version": 1, "plan_decision": saved},
                                         allow_nan=False, separators=(",", ":"))
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                    temporary.write_text(encoded, encoding="utf-8")
                    temporary.replace(self.path)
                    self._evidence = saved
            except (OSError, ValueError, TypeError, RecursionError):
                pass
            return current
        if self._evidence is None:
            return current
        return retain_plan_decision(current, {"plan_decision": self._evidence})
