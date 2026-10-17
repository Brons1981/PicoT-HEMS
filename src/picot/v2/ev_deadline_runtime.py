"""Bounded advisory worker. Has no commitment store or execution capability."""

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
    ) -> None:
        self.read, self.publish, self.configuration, self.now = read, publish, configuration, now
        self.lock = Lock()
        self.last_attempt: datetime | None = None

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
        advice = advise(snapshot, request, self.configuration(snapshot))
        # Reject a changed/cancelled request before publishing an expensive result.
        current = self.read().get("request")
        if current != request or (self.now() - snapshot.captured_at).total_seconds() > 240:
            return
        self.publish(advice)


def home_assistant_advisor(
    token: str, configuration: Callable[[PlanningInputSnapshot], StorageConversionModel],
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
    )
