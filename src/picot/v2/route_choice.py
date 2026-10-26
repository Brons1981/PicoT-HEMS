"""Durable, assignment-scoped route consent; never a price or execution authority.

Mutations share the caller's planning barrier with plan publication. Tokens
identify a single offer; public status is served only through the existing dashboard boundary.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from secrets import token_urlsafe
from typing import Any, cast

from picot.domain.execution_plan import ExecutionPlan
from picot.v2.daily_charge_assignment import DailyChargeAssignment
from picot.v2.daily_recalculation import DailyMainRecalculationTrigger
from picot.v2.route_choice_input import RouteChoiceInput


def _aware(at: datetime) -> None:
    if at.utcoffset() is None:
        raise ValueError("route choice requires timezone-aware timestamps")


class RouteChoiceStoreMixin:
    """Storage extension used only by ActivePlanCommitmentStore."""

    def _read_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def _load_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def _write(self, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def load_daily_assignments(self) -> tuple[DailyChargeAssignment, ...]:
        raise NotImplementedError

    @staticmethod
    def _finish_daily_recalculation(
        payload: dict[str, Any],
        *,
        request_id: str,
        assignment_id: str,
        status: str,
        reason: str,
        plan_id: str | None,
        snapshot_id: str,
    ) -> None:
        raise NotImplementedError

    def _choice_owner(self, assignment_id: str, at: datetime) -> DailyChargeAssignment:
        _aware(at)
        owner = next(
            (a for a in self.load_daily_assignments() if a.assignment_id == assignment_id), None
        )
        if owner is None or owner.completed_at is not None or owner.ends_at <= at:
            raise ValueError("route choice assignment is completed, expired or missing")
        if not owner.route_plan_id:
            raise ValueError("route choice requires an existing bound route")
        return owner

    def offer_route_choice(
        self,
        *,
        assignment_id: str,
        plan_id: str,
        revision: int,
        offer: dict[str, Any],
        expires_at: datetime,
        created_at: datetime,
    ) -> dict[str, Any]:
        """Persist one reviewable alternative; repeated publication is harmless."""
        import json

        _aware(expires_at)
        owner = self._choice_owner(assignment_id, created_at)
        if (owner.route_plan_id, owner.revision) != (plan_id, revision):
            raise ValueError("route choice offer must match the current plan revision")
        if not created_at < expires_at <= owner.ends_at or not offer:
            raise ValueError("route choice requires a future expiry and explicit alternative")
        copied = json.loads(json.dumps(offer, allow_nan=False))
        payload = self._load_payload()
        records = payload.setdefault("route_choices", {})
        previous = [r for r in records.values() if r["assignment_id"] == assignment_id]
        for record in reversed(previous):
            if record["status"] in {"selected", "pending"}:
                return deepcopy(record)
            if (record["plan_id"], record["revision"], record["offer"]) == (
                plan_id,
                revision,
                copied,
            ):
                return deepcopy(record)
        for record in previous:
            if record["status"] == "offered":
                record["status"] = "superseded"
        token = token_urlsafe(32)
        record = {
            "token": token,
            "assignment_id": assignment_id,
            "plan_id": plan_id,
            "revision": revision,
            "offer": copied,
            "status": "offered",
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        records[token] = record
        self._write(payload)
        return deepcopy(record)

    def planning_route_choices(
        self, assignments: tuple[DailyChargeAssignment, ...], at: datetime,
    ) -> tuple[RouteChoiceInput, ...]:
        """Capture all relevant consent from one payload read, without mutations."""
        _aware(at)
        owners = {a.assignment_id for a in assignments
                  if a.completed_at is None and a.ends_at > at and a.route_plan_id}
        latest: dict[tuple[str, str], RouteChoiceInput] = {}
        for record in self._read_payload().get("route_choices", {}).values():
            if record["assignment_id"] in owners and record["status"] in {"pending", "selected"}:
                choice = RouteChoiceInput.from_record(record)
                latest[(choice.assignment_id, choice.status)] = choice
        return tuple(latest[key] for key in sorted(latest))

    def pending_route_choice(self, assignment_id: str) -> dict[str, Any] | None:
        records = self._read_payload().get("route_choices", {})
        pending = [
            r
            for r in records.values()
            if r["assignment_id"] == assignment_id and r["status"] == "pending"
        ]
        return deepcopy(pending[-1]) if pending else None

    def active_route_choice(self, assignment_id: str, at: datetime) -> dict[str, Any] | None:
        """Completion/day end ends consent; safety plan revisions do not."""
        try:
            self._choice_owner(assignment_id, at)
        except ValueError:
            return None
        records = self._read_payload().get("route_choices", {})
        active = [
            r
            for r in records.values()
            if r["assignment_id"] == assignment_id and r["status"] == "selected"
        ]
        return deepcopy(active[-1]) if active else None

    def route_choice_status(self, at: datetime) -> dict[str, Any]:
        _aware(at)
        choices = []
        latest = {}
        for r in self._read_payload().get("route_choices", {}).values():
            latest[r["assignment_id"]] = r
        for stored in latest.values():
            record = deepcopy(stored)
            if record["status"] in {"selected", "pending", "offered"}:
                try:
                    owner = self._choice_owner(record["assignment_id"], at)
                    record["current_plan_id"] = owner.route_plan_id
                    record["current_revision"] = owner.revision
                    record["current_revision_reason"] = (
                        owner.revision_reason.value if owner.revision_reason else None
                    )
                except ValueError:
                    record["status"] = "expired"
                if (
                    record["status"] in {"pending", "offered"}
                    and datetime.fromisoformat(record["expires_at"]) <= at
                ):
                    record["status"] = "expired"
            choices.append(record)
        return {"choices": choices}

    def _queue_choice_recalculation(
        self,
        payload: dict[str, Any],
        *,
        assignment_id: str,
        request_id: str,
        requested_at: datetime,
        token: str | None = None,
    ) -> None:
        previous = payload.get("daily_recalculation", {})
        if previous.get("status") == "pending":
            raise ValueError("another planning request is still pending")
        if previous.get("request_id"):
            payload.setdefault("daily_recalculation_history", {})[previous["request_id"]] = previous
        payload["daily_recalculation"] = {
            "request_id": request_id,
            "requested_at": requested_at.isoformat(),
            "pending_assignment_ids": [assignment_id],
            "status": "pending",
            "results": {},
            "history_preserved": True,
            "route_choice_token": token,
        }

    def request_route_choice(
        self,
        *,
        token: str,
        action: str,
        requested_at: datetime,
    ) -> dict[str, Any]:
        _aware(requested_at)
        if action not in {"pv", "automatic"}:
            raise ValueError("unknown route choice action")
        payload = self._load_payload()
        record = payload.get("route_choices", {}).get(token)
        if record is None:
            raise ValueError("unknown route choice offer")
        if record["status"] in {"pending", "selected", "declined", "released", "rejected"}:
            # Duplicate/replayed actions can never acquire new authority.
            return deepcopy(record)
        if record["status"] != "offered":
            raise ValueError("route choice offer was superseded")
        if action == "pv" and not isinstance(record["offer"].get("alternative"), dict):
            raise ValueError("this offer has no selectable PV alternative")
        owner = self._choice_owner(record["assignment_id"], requested_at)
        if (owner.route_plan_id, owner.revision) != (record["plan_id"], record["revision"]):
            raise ValueError("route choice offer refers to a superseded plan")
        if requested_at >= datetime.fromisoformat(record["expires_at"]):
            raise ValueError("route choice offer has expired")
        if requested_at < datetime.fromisoformat(record["created_at"]):
            raise ValueError("route choice cannot precede its offer")
        record["requested_at"] = requested_at.isoformat()
        record["action"] = action
        if action == "automatic":
            record["status"] = "declined"
        else:
            self._queue_choice_recalculation(
                payload,
                assignment_id=owner.assignment_id,
                request_id="route-choice:" + token,
                requested_at=requested_at,
                token=token,
            )
            record["status"] = "pending"
        self._write(payload)
        return deepcopy(record)

    def release_route_choice(
        self,
        *,
        assignment_id: str,
        requested_at: datetime,
        request_id: str,
    ) -> dict[str, Any]:
        _aware(requested_at)
        if not request_id.strip():
            raise ValueError("release requires request identity")
        payload = self._load_payload()
        records = [
            r
            for r in payload.get("route_choices", {}).values()
            if r["assignment_id"] == assignment_id and r["status"] == "selected"
        ]
        if not records:
            return {"assignment_id": assignment_id, "status": "not_applicable"}
        owner = self._choice_owner(assignment_id, requested_at)
        self._queue_choice_recalculation(
            payload,
            assignment_id=owner.assignment_id,
            request_id=request_id,
            requested_at=requested_at,
        )
        record = records[-1]
        record["status"] = "released"
        record["released_at"] = requested_at.isoformat()
        record["release_request_id"] = request_id
        self._write(payload)
        return deepcopy(record)

    def reject_route_choice(
        self,
        *,
        token: str,
        reason: str,
        at: datetime | None = None,
    ) -> dict[str, Any]:
        payload = self._load_payload()
        record = payload.get("route_choices", {}).get(token)
        if record is None:
            raise ValueError("unknown route choice offer")
        if record["status"] != "pending":
            return deepcopy(record)
        request = payload.get("daily_recalculation", {})
        if request.get("route_choice_token") != token or request.get("status") != "pending":
            raise ValueError("route choice no longer owns the pending request")
        owner = next(
            (
                a
                for a in self.load_daily_assignments()
                if a.assignment_id == record["assignment_id"]
            ),
            None,
        )
        self._finish_daily_recalculation(
            payload,
            request_id=request["request_id"],
            assignment_id=record["assignment_id"],
            status="retained",
            reason=reason,
            plan_id=owner.route_plan_id if owner else None,
            snapshot_id="route-choice-rejected",
        )
        record["status"] = "rejected"
        record["reason"] = reason
        if at is not None:
            _aware(at)
            record["resolved_at"] = at.isoformat()
        self._write(payload)
        return deepcopy(record)

    def record_route_choice_notice(
        self,
        *,
        assignment_id: str,
        key: str,
        message: str,
        at: datetime,
    ) -> dict[str, Any] | None:
        """Persist deduplicated proposal/repair information without changing consent."""
        _aware(at)
        if not key.strip() or not message.strip():
            raise ValueError("route choice notice requires a key and message")
        active = self.active_route_choice(assignment_id, at)
        if active is None:
            return None
        if active.get("last_notice", {}).get("key") == key:
            return active
        payload = self._load_payload()
        record = payload["route_choices"][active["token"]]
        record["last_notice"] = {"key": key, "message": message, "at": at.isoformat()}
        self._write(payload)
        return cast(dict[str, Any], deepcopy(record))

    def _accept_route_choice(
        self,
        payload: dict[str, Any],
        trigger: DailyMainRecalculationTrigger,
        bound: DailyChargeAssignment,
        plan: ExecutionPlan,
    ) -> None:
        token = trigger.request.route_choice_token
        record = payload.get("route_choices", {}).get(token)
        if (
            record is None
            or record["status"] != "pending"
            or (record["assignment_id"], record["plan_id"], record["revision"])
            != (bound.assignment_id, trigger.route_plan_id, trigger.revision)
        ):
            raise ValueError("route choice must own the current assignment revision")
        if datetime.fromisoformat(record["expires_at"]) <= plan.created_at:
            raise ValueError("route choice expired before acceptance")
        record.update(
            {
                "status": "selected",
                "accepted_at": plan.created_at.isoformat(),
                "accepted_plan_id": plan.plan_id,
                "accepted_revision": bound.revision,
                "selected_main_windows": [
                    {"starts_at": s.starts_at.isoformat(), "ends_at": s.ends_at.isoformat()}
                    for s in bound.main_segments
                ],
            }
        )
