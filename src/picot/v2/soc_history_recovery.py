"""Bounded HA recorder evidence for missed main-charge completion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


class HistoricalSOCRecovery:
    """Read raw SOC states; never infer full from rounding or a forecast."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.last_attempt: dict[str, datetime] = {}
        self.status = "not_checked"

    def recover(
        self,
        store: ActivePlanCommitmentStore,
        *,
        entity_id: str,
        execution_scope_id: str,
        now: datetime,
    ) -> None:
        if not entity_id:
            self.status = "soc_entity_missing"
            return
        owners = tuple(
            a
            for a in store.load_daily_assignments()
            if a.execution_scope_id == execution_scope_id
            and a.completed_at is None
            and a.route_plan_id is not None
            and a.starts_at < now < a.ends_at
        )
        for owner in owners:
            last = self.last_attempt.get(owner.assignment_id)
            if last is not None and now - last < timedelta(minutes=5):
                continue
            self.last_attempt[owner.assignment_id] = now
            start = max(owner.starts_at, owner.created_at)
            if start >= now:
                continue
            query = urlencode(
                {"filter_entity_id": entity_id, "end_time": now.isoformat(), "no_attributes": "1"}
            )
            request = Request(
                "http://supervisor/core/api/history/period/"
                + quote(start.isoformat(), safe="")
                + "?"
                + query,
                headers={"Authorization": f"Bearer {self.token}"},
                method="GET",
            )
            try:
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise ValueError("invalid SOC history payload")
                self.status = "no_matching_full_observation"
                samples = []
                for group in payload:
                    if not isinstance(group, list):
                        continue
                    for row in group:
                        if not isinstance(row, dict) or row.get("entity_id") != entity_id:
                            continue
                        try:
                            soc = float(row["state"])
                            at = datetime.fromisoformat(row["last_changed"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        if soc == 100.0 and at.utcoffset() is not None and start <= at <= now:
                            samples.append(at)
                for at in sorted(set(samples)):
                    evidence = (
                        "ha-soc-history:"
                        + sha256(f"{entity_id}|{at.isoformat()}|100".encode()).hexdigest()
                    )
                    completed = store.recover_historical_main_completion(
                        assignment_id=owner.assignment_id,
                        measured_at=at,
                        observed_at=now,
                        soc=1.0,
                        evidence_id=evidence,
                    )
                    if completed is not None and completed.completed_at is not None:
                        self.status = "historical_main_completion_recovered"
                        break
            except (URLError, OSError, ValueError) as exc:
                self.status = "soc_history_unavailable:" + type(exc).__name__
