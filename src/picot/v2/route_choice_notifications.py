"""Asynchronous HA notification transport; HEMS alone accepts route choices.

The input_text helper is a mailbox, never authority. Its state is not cleared:
clearing could erase a newer click. Durable offer validation belongs to on_choice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Thread
from typing import Any
from urllib.request import Request, urlopen

EVENT_TYPE = "picot_route_choice"
MAILBOX_PATTERN = re.compile(r"input_text\.[a-z0-9_]+\Z")


def publish_choice_status(notifier: RouteChoiceNotifier, view: dict[str, Any]) -> None:
    """Project persisted planner facts into deduplicated messages."""
    labels = {
        "offered": "Laadroute beoordelen",
        "pending": "Routekeuze ontvangen",
        "selected": "PV-route bevestigd",
        "rejected": "Routekeuze niet overgenomen",
        "released": "PicoT kiest weer automatisch",
        "declined": "Automatisch plan behouden",
    }
    for record in view.get("choices", []):
        status = record["status"]
        if status not in labels:
            continue
        offer = record.get("offer", {})
        message = (
            labels[status] + ". Opdracht " + offer.get("delivery_date", record["assignment_id"])
        )
        if status == "offered":
            for name in ("automatic", "alternative"):
                route = offer.get(name)
                if route:
                    message += (
                        f"\n{route['label']}: {', '.join(route.get('windows', []))}; "
                        f"net {route['grid_import_kwh']:.2f} kWh; "
                        f"PV naar batterij {route['pv_storage_kwh']:.2f} kWh."
                    )
        if status == "pending":
            message += ". HEMS controleert de route met actuele gegevens."
        if record.get("reason"):
            message += ". " + record["reason"]
        notifier.publish(
            record["token"] + ":" + status,
            labels[status],
            message,
            offer_id=record["token"] if status == "offered" and offer.get("alternative") else None,
            expires_at=record["expires_at"] if status in {"offered", "pending"} else None,
            tag="picot_route_" + record["assignment_id"],
        )
        notice = record.get("last_notice")
        if notice and status == "selected":
            notifier.publish(
                record["token"] + ":" + notice["key"],
                "Laadroute opnieuw beoordeeld",
                notice["message"],
                tag="picot_route_" + record["assignment_id"],
            )


class RouteChoiceNotifier:
    """Persist outbound events and receive bounded, authenticated HA mailbox data."""

    def __init__(
        self,
        token: str,
        path: Path,
        *,
        mailbox_entity: str = "",
        on_choice: Callable[[dict[str, str]], dict[str, Any]] | None = None,
        enabled: bool = True,
    ) -> None:
        if mailbox_entity and not MAILBOX_PATTERN.fullmatch(mailbox_entity):
            raise ValueError("route choice mailbox must be an input_text entity")
        self.token, self.path = token, path
        self.mailbox_entity, self.on_choice = mailbox_entity, on_choice
        self.enabled = enabled and bool(token)
        self._condition = Condition()
        self._stopped = False
        self._wake_version = 0
        self._pending: list[dict[str, Any]] = []
        self._published: list[str] = []
        self._last_response: str | None = None
        self._thread: Thread | None = None
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(saved, dict)
                or not isinstance(saved.get("pending"), list)
                or not isinstance(saved.get("published"), list)
            ):
                raise ValueError("invalid route notification state")
            self._pending = [
                item
                for item in saved["pending"]
                if isinstance(item, dict) and isinstance(item.get("event_id"), str)
            ]
            self._published = [item for item in saved["published"] if isinstance(item, str)]
            last = saved.get("last_response")
            self._last_response = last if isinstance(last, str) else None
        except (OSError, ValueError, TypeError):
            self._pending, self._published = [], []

    @property
    def choices_enabled(self) -> bool:
        return self.enabled and bool(self.mailbox_entity) and self.on_choice is not None

    def start(self) -> None:
        with self._condition:
            if not self.enabled or self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="hems-route-choice", daemon=True)
            self._thread.start()

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    stop = close

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "pending": self._pending,
                    "published": self._published[-2048:],
                    "last_response": self._last_response,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def publish(
        self,
        event_id: str,
        title: str,
        message: str,
        *,
        offer_id: str | None = None,
        expires_at: datetime | str | None = None,
        tag: str = "picot_hems_route_choice",
    ) -> bool:
        """Queue once. Never perform network I/O on the planning thread."""
        if not self.enabled:
            return False
        if not event_id or not title or not message:
            raise ValueError("route notification identity and text are required")
        if offer_id is not None and (not offer_id or len(offer_id) > 128):
            raise ValueError("route offer identity must fit the HA mailbox")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at is not None and expires_at.utcoffset() is None:
            raise ValueError("route notification expiry must be timezone aware")
        event = {
            "event_id": event_id,
            "title": title,
            "message": message,
            "tag": tag,
            "offer_id": offer_id if self.choices_enabled else None,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "response_entity": self.mailbox_entity,
        }
        with self._condition:
            if event_id in self._published:
                return True
            if len(self._pending) >= 256:
                return False
            previous_published = self._published
            self._published = [*self._published[-2047:], event_id]
            self._pending.append(event)
            try:
                self._save()
            except OSError:
                self._pending.pop()
                self._published = previous_published
                return False
            self._wake_version += 1
            self._condition.notify_all()
        return True

    def _request(self, path: str, data: dict[str, Any] | None = None) -> Any:
        request = Request(
            "http://supervisor/core/api/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            method="POST" if data is not None else "GET",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def _send(self, event: dict[str, Any]) -> None:
        self._request("events/" + EVENT_TYPE, event)

    def _poll(self) -> None:
        if not self.choices_enabled:
            return
        envelope = self._request("states/" + self.mailbox_entity)
        raw = envelope.get("state") if isinstance(envelope, dict) else None
        if (
            not isinstance(raw, str)
            or len(raw) > 255
            or raw == self._last_response
            or raw in {"", "unknown", "unavailable"}
        ):
            return
        try:
            value = json.loads(raw)
        except ValueError:
            return
        if not isinstance(value, dict) or value.get("action") not in {"pv", "automatic"}:
            return
        offer, request_id = value.get("token"), value.get("request_id")
        if (
            not isinstance(offer, str)
            or not 1 <= len(offer) <= 128
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 64
        ):
            return
        assert self.on_choice is not None
        self.on_choice({"token": offer, "action": value["action"], "request_id": request_id})
        # The core callback must durably consume/decline the request before returning.
        # If transport persistence fails, the core's request identity makes retry safe.
        with self._condition:
            self._last_response = raw
            self._save()

    def refresh(self) -> None:
        """One bounded transport pass, exposed for deterministic boundary tests."""
        # A failed outgoing notification must not prevent an incoming choice.
        try:
            self._poll()
        except Exception:
            pass  # Retry next pass; network/callback failures never interrupt control.
        with self._condition:
            event = self._pending[0] if self._pending else None
        if event is None:
            return
        expiry = event.get("expires_at")
        expired = expiry is not None and datetime.fromisoformat(expiry) <= datetime.now(UTC)
        if not expired:
            self._send(event)
        with self._condition:
            self._pending.pop(0)
            try:
                self._save()
            except OSError:
                self._pending.insert(0, event)
                raise

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._stopped:
                    return
                wake_version = self._wake_version
            try:
                self.refresh()
            except Exception:
                pass  # Durable queue retries; notification failure has no plan authority.
            with self._condition:
                if self._stopped:
                    return
                if wake_version == self._wake_version:
                    self._condition.wait(timeout=5)
