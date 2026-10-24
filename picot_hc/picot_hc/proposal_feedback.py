"""Consume matching HEMS rejection conditions without inventing comfort evidence."""

import copy
from datetime import datetime

from .energy_portfolio import REQUEST_ENTITY, read_assessment


class ProposalFeedback:
    def __init__(self):
        self.basis = None
        self.until = None
        self.end = None
        self.blocked = False
        self.handled = []
        self.reason = None
        self.conditions = []

    def receive(self, states, request, outlook, now):
        basis = (
            outlook.get("snapshot_id"),
            (outlook.get("replacement_basis") or {}).get("basis_id"),
        )
        if basis != self.basis:
            self.conditions = []
            self.basis, self.until, self.end, self.blocked, self.reason = (
                basis,
                None,
                None,
                False,
                None,
            )
        if not request or states.get(REQUEST_ENTITY, {}).get("attributes") != request:
            return False
        if (request.get("basis_snapshot_id"), request.get("replacement_basis_id")) != basis:
            return False
        answer = read_assessment(states, now)
        if answer["status"] not in ("rejected", "blocked") or request["request_id"] in self.handled:
            return False
        self.handled = (self.handled + [request["request_id"]])[-32:]
        self.until = answer.get("valid_until", now)
        self.blocked = True
        self.reason = (
            "HEMS vraagt een nieuw profiel; passend comfort- en verbruiksbewijs ontbreekt."
        )
        rows = answer["assessments"]
        self.conditions = [copy.deepcopy(r.get("constraint")) for r in rows if r.get("constraint")]
        expected = {p["plan_id"] for p in request["plans"]}
        if (
            answer["status"] == "rejected"
            and len(rows) == len(expected)
            and {r["plan_id"] for r in rows} == expected
            and all(r["status"] == "rejected" for r in rows)
        ):
            ends = []
            try:
                for row in rows:
                    condition = row.get("constraint", {})
                    if condition.get("kind") != "end_before":
                        raise ValueError("requires new measured profile")
                    stamp = datetime.fromisoformat(condition["ends_at"].replace("Z", "+00:00"))
                    if stamp.utcoffset() is None or stamp.timestamp() <= now:
                        raise ValueError("invalid horizon")
                    ends.append(stamp.timestamp())
                end = min(ends)
                # A repeat rejection must actually tighten the previous horizon.
                if self.end is None or end < self.end:
                    self.end, self.blocked = end, False
                    self.reason = "Nieuw voorstel binnen de door HEMS opgegeven eindtijd."
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
        return True

    def limit(self, end):
        return min(end, self.end) if self.end is not None else end

    def view(self):
        return copy.deepcopy(
            dict(reason=self.reason, ends_at=self.end, valid_until=self.until, blocked=self.blocked)
        )
