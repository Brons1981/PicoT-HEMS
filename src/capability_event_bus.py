"""Deterministic in-process event bus for PicoT HEMS capability events.

The event bus transports already-decided facts between components. It never
interprets events, changes mappings, requests selection, or makes planning
choices. Delivery is synchronous and follows subscription order so behaviour is
reproducible and straightforward to audit.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

_SCHEMA = "picot_hems.capability.event"
_SCHEMA_VERSION = "1.0.0"
_BUS_VERSION = "0.1.0"
_WILDCARD = "*"


class EventBusError(ValueError):
    """Raised when an event-bus contract would be violated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class CapabilityEventBus:
    """Publish immutable capability events to ordered synchronous subscribers."""

    def __init__(
        self,
        *,
        now: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self._now = now
        self._id_factory = id_factory
        self._subscriptions: list[dict[str, Any]] = []
        self._subscriber_ids: set[str] = set()
        self._published: list[dict[str, Any]] = []

    def subscribe(
        self,
        *,
        subscriber_id: str,
        event_type: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Register one ordered subscriber for an event type or ``*``."""
        normalized_id = str(subscriber_id or "").strip()
        normalized_type = str(event_type or "").strip().upper()
        if not normalized_id:
            raise EventBusError("subscriber_id is required")
        if normalized_id in self._subscriber_ids:
            raise EventBusError("subscriber_id is already registered")
        if not normalized_type:
            raise EventBusError("event_type is required")
        if not callable(handler):
            raise EventBusError("handler must be callable")

        subscription = {
            "subscriber_id": normalized_id,
            "event_type": normalized_type,
            "subscription_order": len(self._subscriptions) + 1,
        }
        self._subscriptions.append({**subscription, "handler": handler})
        self._subscriber_ids.add(normalized_id)
        return deepcopy(subscription)

    def publish(
        self,
        *,
        event_type: str,
        capability_id: str,
        capability_role: str = "primary",
        payload: dict[str, Any] | None = None,
        source_component: str,
        causation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish one immutable event and synchronously deliver private copies."""
        normalized_type = str(event_type or "").strip().upper()
        if not normalized_type:
            raise EventBusError("event_type is required")
        if not capability_id:
            raise EventBusError("capability_id is required")
        if not capability_role:
            raise EventBusError("capability_role is required")
        if not source_component:
            raise EventBusError("source_component is required")

        event_id = self._id_factory("evt")
        envelope = {
            "event_id": event_id,
            "schema": _SCHEMA,
            "schema_version": _SCHEMA_VERSION,
            "bus_version": _BUS_VERSION,
            "event_type": normalized_type,
            "capability_id": capability_id,
            "capability_role": capability_role,
            "source_component": source_component,
            "published_at": self._now(),
            "causation_id": causation_id,
            "correlation_id": correlation_id or event_id,
            "payload": deepcopy(payload or {}),
            "immutable": True,
        }

        deliveries: list[dict[str, Any]] = []
        for subscription in self._subscriptions:
            if subscription["event_type"] not in {normalized_type, _WILDCARD}:
                continue
            subscriber_id = subscription["subscriber_id"]
            try:
                subscription["handler"](deepcopy(envelope))
            except Exception as exc:  # delivery failure must remain auditable
                deliveries.append(
                    {
                        "subscriber_id": subscriber_id,
                        "status": "FAILED",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
            else:
                deliveries.append(
                    {
                        "subscriber_id": subscriber_id,
                        "status": "DELIVERED",
                        "error_type": None,
                        "error_message": None,
                    }
                )

        publication = {
            "event": envelope,
            "delivery": {
                "attempted": len(deliveries),
                "delivered": sum(item["status"] == "DELIVERED" for item in deliveries),
                "failed": sum(item["status"] == "FAILED" for item in deliveries),
                "results": deliveries,
            },
        }
        self._published.append(publication)
        return deepcopy(publication)

    def get_publications(
        self,
        *,
        event_type: str | None = None,
        capability_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return immutable publication copies, optionally filtered."""
        publications = self._published
        if event_type is not None:
            normalized_type = event_type.upper()
            publications = [
                item for item in publications if item["event"]["event_type"] == normalized_type
            ]
        if capability_id is not None:
            publications = [
                item for item in publications if item["event"]["capability_id"] == capability_id
            ]
        return deepcopy(publications)

    def get_subscriptions(self) -> list[dict[str, Any]]:
        """Return subscription metadata without exposing handler callables."""
        return [
            {
                "subscriber_id": item["subscriber_id"],
                "event_type": item["event_type"],
                "subscription_order": item["subscription_order"],
            }
            for item in self._subscriptions
        ]
