"""Read-only original daily charging and trading plan projection; never a planning input."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MAX_REFERENCE_BYTES = 32_000_000


class PricePlanReference:
    """Recover initial charging plus original market segments from durable lineage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._signature: tuple[int, int] | None = None
        self._view: dict[str, Any] = {"status": "unavailable", "plans": []}

    def read(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature == self._signature:
                return self._view
            with self.path.open("rb") as source:
                raw = source.read(MAX_REFERENCE_BYTES + 1)
            if len(raw) > MAX_REFERENCE_BYTES:
                raise ValueError("reference size limit")
            payload = json.loads(raw)
            records = list(payload.get("daily_main_history", {}).values())
            for key, assignment in payload.get("daily_assignments", {}).items():
                plan = payload.get("daily_execution_plans", {}).get(key)
                if plan is not None:
                    records.append({"assignment": assignment, "plan": plan})
            plans = []
            for record in records:
                owner, plan = record["assignment"], record["plan"]
                if owner.get("revision") != 1:
                    continue
                if (owner.get("revision_reason") != "initial_main_route"
                        or owner["route_plan_id"] != plan["plan_id"]
                        or owner["execution_scope_id"] != plan["execution_scope_id"]
                        or owner["revision_evidence_id"] != plan["evaluation_id"]):
                    raise ValueError("original plan lineage mismatch")
                start = datetime.fromisoformat(owner["delivery_date"]).replace(
                    tzinfo=ZoneInfo(owner["timezone"])
                )
                ends = start + timedelta(days=1)
                segments = []
                for segment in plan["segments"]:
                    a = datetime.fromisoformat(segment["starts_at"])
                    b = datetime.fromisoformat(segment["ends_at"])
                    if a.utcoffset() is None or b.utcoffset() is None or a >= b:
                        raise ValueError("invalid original interval")
                    a, b = max(a, start), min(b, ends)
                    if a < b:
                        segments.append({
                            **{k: segment.get(k) for k in (
                                "primitive", "requested_power_w", "charge_source_policy"
                            )},
                            "starts_at": a.isoformat(), "ends_at": b.isoformat(),
                        })
                market_ids = []
                for key, binding in payload.get("market_plan_bindings", {}).items():
                    market_owner = payload.get("market_daily_assignments", {})[key]
                    if (market_owner["execution_scope_id"] != plan["execution_scope_id"]
                            or market_owner["delivery_date"] != owner["delivery_date"]):
                        continue
                    market_id, market_segments = _original_market_segments(
                        payload, key, binding, plan["execution_scope_id"], start, ends
                    )
                    for market_segment in market_segments:
                        segments = _overlay_segment(segments, market_segment)
                    market_ids.append(market_id)
                plans.append({
                    "plan_id": plan["plan_id"],
                    "execution_scope_id": plan["execution_scope_id"],
                    "delivery_date": owner["delivery_date"],
                    "segments": segments,
                    "market_plan_ids": market_ids,
                })
            self._view = {"status": "available" if plans else "unavailable", "plans": plans}
            self._signature = signature
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._view = {"status": "unavailable", "plans": []}
            self._signature = None
        return self._view



def _original_market_segments(
    payload: dict[str, Any], key: str, binding: dict[str, Any], scope: str,
    start: datetime, end: datetime,
) -> tuple[str, list[dict[str, Any]]]:
    """Only bound trade segments; never copy later charging from a shared plan."""
    original_id = binding.get("original_plan_id")
    original_segments = binding.get("original_segment_ids")
    if bool(original_id) != bool(original_segments):
        raise ValueError("incomplete original market lineage")
    plan_id = original_id or binding["plan_id"]
    segment_ids = original_segments or binding["segment_ids"]
    plan = payload["execution_plans"][plan_id]
    if (binding["assignment_id"] != key or binding["execution_scope_id"] != scope
            or plan["execution_scope_id"] != scope or plan["plan_id"] != plan_id):
        raise ValueError("market reference identity mismatch")
    parts = [s for s in plan["segments"] if s["segment_id"] in segment_ids]
    if not parts or [s["segment_id"] for s in parts] != segment_ids:
        raise ValueError("original market segments missing")
    result = []
    previous = None
    for part in parts:
        a, b = datetime.fromisoformat(part["starts_at"]), datetime.fromisoformat(part["ends_at"])
        if (a.utcoffset() is None or b.utcoffset() is None or not start <= a < b <= end
                or (previous is not None and a != previous)
                or part["purpose"] != key or part["primitive"] != "discharge_at_power"
                or part.get("main_assignment_id") is not None):
            raise ValueError("invalid original market segment")
        previous = b
        result.append({k: part.get(k) for k in (
            "starts_at", "ends_at", "primitive", "requested_power_w", "charge_source_policy"
        )})
    return plan_id, result


def _overlay_segment(
    segments: list[dict[str, Any]], market: dict[str, Any],
) -> list[dict[str, Any]]:
    """Display original trade in place of original household support, without overlaps."""
    start = datetime.fromisoformat(market["starts_at"])
    end = datetime.fromisoformat(market["ends_at"])
    result = []
    for segment in segments:
        a = datetime.fromisoformat(segment["starts_at"])
        b = datetime.fromisoformat(segment["ends_at"])
        if b <= start or a >= end:
            result.append(segment)
            continue
        if a < start:
            result.append({**segment, "ends_at": market["starts_at"]})
        if end < b:
            result.append({**segment, "starts_at": market["ends_at"]})
    return sorted([*result, market], key=lambda s: datetime.fromisoformat(s["starts_at"]))
