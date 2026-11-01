"""Passive advice worker and explicit main-loop joint-plan acceptance."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock, Thread
from typing import Any
from urllib.request import Request, urlopen

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.ev_deadline_advice import advise
from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.projection import Card


class EVDeadlineAdvisor:
    def __init__(
        self, *, read: Callable[[], dict[str, Any]],
        publish: Callable[[dict[str, Any]], None],
        configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        adopt: Callable[[Any, PlanningInputSnapshot], dict[str, Any]] | None = None,
        receipt: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.read, self.publish, self.configuration, self.now = read, publish, configuration, now
        self.lock = Lock()
        self.last_attempt: datetime | None = None
        self.adopt, self.receipt = adopt, receipt
        self.selections: dict[str, Any] = {}

    def accept_pending(self, snapshot: PlanningInputSnapshot) -> bool:
        """Called only by the main planning loop; never from the advisory worker."""
        if self.adopt is None or not self.lock.acquire(blocking=False):
            return False
        selected: Any = None
        ownership_changed = False
        try:
            envelope = self.read()
            request = envelope.get("request")
            selected = envelope.get("selected_advice")
            if (not isinstance(request, dict) or request.get("state") != "accepted"
                    or not isinstance(selected, dict) or not selected.get("selection_id")):
                return False
            published = datetime.fromisoformat(str(envelope.get("generated_at", "")))
            if (published.tzinfo is None
                    or not 0 <= (self.now() - published).total_seconds() <= 60
                    or not 0 <= (self.now() - snapshot.captured_at).total_seconds() <= 120
                    or any(selected.get(k) != request.get(k)
                           for k in ("session_id", "request_revision"))):
                return False
            selection_id = str(selected["selection_id"])
            slots = selected.get("slots", [])
            if slots and datetime.fromisoformat(slots[0]["starts_at"]) < self.now():
                raise ValueError("joint_ev_slot_requires_fresh_advice")
            committed = self.receipt(selection_id) if self.receipt else None
            if committed is None:
                proof = self.selections.get(selection_id)
                if proof is None:
                    raise ValueError("joint_selection_expired_request_new_advice")
                current = self.read()
                if (current.get("request") != request
                        or current.get("selected_advice") != selected):
                    return False
                committed = self.adopt(proof, snapshot)
                ownership_changed = True
            if any(committed.get(k) != selected.get(k)
                   for k in ("selection_id", "session_id", "request_revision")):
                raise ValueError("joint_receipt_identity_mismatch")
            self.publish(selected | committed | {"execution_status": "committed",
                                                  "committed_at": self.now().isoformat()})
            return True
        except (ValueError, OSError, TypeError) as exc:
            print(json.dumps({"event": "ev_joint_acceptance_failed", "error": str(exc)}),
                  flush=True)
            if isinstance(selected, dict):
                try:
                    self.publish(selected | {"execution_status": "blocked", "reason": str(exc)})
                except (OSError, ValueError):
                    pass
            return ownership_changed
        finally:
            self.lock.release()

    def submit(self, snapshot: PlanningInputSnapshot) -> None:
        now = self.now()
        if self.last_attempt is not None and now - self.last_attempt < timedelta(seconds=30):
            return
        if not self.lock.acquire(blocking=False):
            return
        self.last_attempt = now

        def work() -> None:
            try:
                self.refresh(snapshot)
            except Exception as exc:
                # A passive calculation/transport failure must never abort physical control.
                print(json.dumps({"event": "ev_deadline_advice_failed", "error": str(exc)}),
                      flush=True)
            finally:
                self.lock.release()

        Thread(target=work, name="ev-deadline-advisor", daemon=True).start()

    def refresh(self, snapshot: PlanningInputSnapshot) -> None:
        envelope = self.read()
        request = envelope.get("request")
        if not isinstance(request, dict) or request.get("state") != "requested":
            return
        published = datetime.fromisoformat(str(envelope.get("generated_at", "")))
        if published.tzinfo is None or not 0 <= (self.now() - published).total_seconds() <= 60:
            return
        if not 0 <= (self.now() - snapshot.captured_at).total_seconds() <= 120:
            return
        selections: dict[str, Any] = {}
        advice = advise(
            snapshot, request, self.configuration(snapshot), selections=selections,
            execution_not_before=lambda: self.now() + timedelta(seconds=60),
        )
        # Reject a changed/cancelled request before publishing an expensive result.
        current = self.read().get("request")
        if current != request or (self.now() - snapshot.captured_at).total_seconds() > 240:
            return
        # Keep recent published choices: a user's click may race the next refresh.
        if len(self.selections) > 20:
            self.selections = dict(list(self.selections.items())[-20:])
        self.selections.update(selections)
        self.publish(advice)


def home_assistant_advisor(
    token: str, configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
    *, adopt: Callable[[Any, PlanningInputSnapshot], dict[str, Any]] | None = None,
    receipt: Callable[[str], dict[str, Any] | None] | None = None,
) -> EVDeadlineAdvisor:
    def read() -> dict[str, Any]:
        request = Request(
            "http://supervisor/core/api/states/sensor.picot_ev_charging_request",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        attributes = payload.get("attributes") if isinstance(payload, dict) else None
        if not isinstance(attributes, dict):
            raise ValueError("EV charging request attributes missing")
        return attributes

    sink = HomeAssistantProjectionSink(token)
    return EVDeadlineAdvisor(
        read=read,
        publish=lambda value: sink.publish(Card(
            "sensor.picot_ev_charging_advice", str(value.get("status", "blocked")), value,
        )),
        configuration=configuration,
        adopt=adopt, receipt=receipt,
    )
