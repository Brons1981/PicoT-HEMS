"""Contract tests for the PicoT HEMS Capability Event Bus."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from capability_event_bus import CapabilityEventBus, EventBusError  # noqa: E402

CAPABILITY_ID = "battery.system.observation.soc"


def _clock() -> Any:
    values = iter(
        [
            "2026-07-29T19:00:00+00:00",
            "2026-07-29T19:01:00+00:00",
            "2026-07-29T19:02:00+00:00",
        ]
    )
    return lambda: next(values)


def _bus() -> CapabilityEventBus:
    ids = iter(["evt_1", "evt_2", "evt_3"])
    return CapabilityEventBus(now=_clock(), id_factory=lambda prefix: next(ids))


def test_publish_creates_immutable_event_envelope() -> None:
    bus = _bus()

    publication = bus.publish(
        event_type="capability_invalidated",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
        payload={"reason": "entity_removed"},
        causation_id="life_1",
    )

    event = publication["event"]
    assert event["event_id"] == "evt_1"
    assert event["event_type"] == "CAPABILITY_INVALIDATED"
    assert event["capability_role"] == "primary"
    assert event["payload"] == {"reason": "entity_removed"}
    assert event["causation_id"] == "life_1"
    assert event["correlation_id"] == "evt_1"
    assert event["immutable"] is True


def test_matching_subscribers_receive_events_in_subscription_order() -> None:
    bus = _bus()
    calls: list[str] = []
    bus.subscribe(
        subscriber_id="audit",
        event_type="CAPABILITY_RESTORED",
        handler=lambda event: calls.append(f"audit:{event['event_id']}"),
    )
    bus.subscribe(
        subscriber_id="planner",
        event_type="CAPABILITY_RESTORED",
        handler=lambda event: calls.append(f"planner:{event['event_id']}"),
    )

    publication = bus.publish(
        event_type="CAPABILITY_RESTORED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )

    assert calls == ["audit:evt_1", "planner:evt_1"]
    assert publication["delivery"]["attempted"] == 2
    assert publication["delivery"]["delivered"] == 2
    assert publication["delivery"]["failed"] == 0


def test_non_matching_subscriber_does_not_receive_event() -> None:
    bus = _bus()
    calls: list[str] = []
    bus.subscribe(
        subscriber_id="planner",
        event_type="CAPABILITY_INVALIDATED",
        handler=lambda event: calls.append(event["event_type"]),
    )

    publication = bus.publish(
        event_type="CAPABILITY_RESTORED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )

    assert calls == []
    assert publication["delivery"]["attempted"] == 0


def test_wildcard_subscriber_receives_all_event_types() -> None:
    bus = _bus()
    calls: list[str] = []
    bus.subscribe(
        subscriber_id="audit",
        event_type="*",
        handler=lambda event: calls.append(event["event_type"]),
    )

    bus.publish(
        event_type="CAPABILITY_TEMPORARILY_UNAVAILABLE",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )
    bus.publish(
        event_type="CAPABILITY_RESTORED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )

    assert calls == ["CAPABILITY_TEMPORARILY_UNAVAILABLE", "CAPABILITY_RESTORED"]


def test_each_subscriber_receives_private_event_copy() -> None:
    bus = _bus()
    observed: list[str] = []

    def mutating_handler(event: dict[str, Any]) -> None:
        event["payload"]["status"] = "CORRUPTED"

    def observing_handler(event: dict[str, Any]) -> None:
        observed.append(event["payload"]["status"])

    bus.subscribe(
        subscriber_id="mutator",
        event_type="CAPABILITY_RESTORED",
        handler=mutating_handler,
    )
    bus.subscribe(
        subscriber_id="observer",
        event_type="CAPABILITY_RESTORED",
        handler=observing_handler,
    )

    publication = bus.publish(
        event_type="CAPABILITY_RESTORED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
        payload={"status": "ACTIVE"},
    )

    assert observed == ["ACTIVE"]
    assert publication["event"]["payload"]["status"] == "ACTIVE"


def test_subscriber_failure_is_isolated_and_audited() -> None:
    bus = _bus()
    calls: list[str] = []

    def broken_handler(event: dict[str, Any]) -> None:
        raise RuntimeError("subscriber unavailable")

    bus.subscribe(
        subscriber_id="broken",
        event_type="CAPABILITY_INVALIDATED",
        handler=broken_handler,
    )
    bus.subscribe(
        subscriber_id="audit",
        event_type="CAPABILITY_INVALIDATED",
        handler=lambda event: calls.append(event["event_id"]),
    )

    publication = bus.publish(
        event_type="CAPABILITY_INVALIDATED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )

    assert calls == ["evt_1"]
    assert publication["delivery"]["delivered"] == 1
    assert publication["delivery"]["failed"] == 1
    assert publication["delivery"]["results"][0] == {
        "subscriber_id": "broken",
        "status": "FAILED",
        "error_type": "RuntimeError",
        "error_message": "subscriber unavailable",
    }


def test_duplicate_subscriber_id_is_rejected() -> None:
    bus = _bus()
    bus.subscribe(subscriber_id="audit", event_type="*", handler=lambda event: None)

    with pytest.raises(EventBusError, match="already registered"):
        bus.subscribe(
            subscriber_id="audit",
            event_type="CAPABILITY_RESTORED",
            handler=lambda event: None,
        )


def test_publication_history_is_returned_as_copy() -> None:
    bus = _bus()
    bus.publish(
        event_type="CAPABILITY_RESTORED",
        capability_id=CAPABILITY_ID,
        source_component="CapabilityLifecycleEngine",
    )

    history = bus.get_publications()
    history[0]["event"]["event_type"] = "CORRUPTED"

    assert bus.get_publications()[0]["event"]["event_type"] == "CAPABILITY_RESTORED"
