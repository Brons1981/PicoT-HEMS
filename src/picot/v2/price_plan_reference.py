"""Read-only first-admitted daily plan projection; never a planning input."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MAX_REFERENCE_BYTES = 32_000_000


class PricePlanReference:
    """Recover revision one from existing durable records, including after restart."""

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
                plans.append({
                    "plan_id": plan["plan_id"],
                    "execution_scope_id": plan["execution_scope_id"],
                    "delivery_date": owner["delivery_date"],
                    "segments": segments,
                })
            self._view = {"status": "available" if plans else "unavailable", "plans": plans}
            self._signature = signature
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._view = {"status": "unavailable", "plans": []}
            self._signature = None
        return self._view
