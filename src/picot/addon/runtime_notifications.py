"""Deduplicated Home Assistant notifications for PicoT runtime failures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0
NOTIFICATION_ID = "picot_runtime_integration_error"


@dataclass(slots=True)
class ActiveRuntimeFailure:
    fingerprint: str
    first_seen: datetime
    count: int = 1


class RuntimeFailureNotifier:
    """Notify on first failure, suppress repeats, and announce recovery."""

    def __init__(self) -> None:
        self._active: ActiveRuntimeFailure | None = None

    def failure(
        self,
        token: str,
        *,
        now: datetime,
        fingerprint: str,
        message: str,
        severity: str = "warning",
        opener=urlopen,
    ) -> None:
        if self._active is not None and self._active.fingerprint == fingerprint:
            self._active.count += 1
            return

        self._active = ActiveRuntimeFailure(fingerprint=fingerprint, first_seen=now)
        self._publish(
            token,
            title=f"PicoT {severity}: integratiefout",
            message=(
                f"{message}\n\nEerste fout: {now.isoformat()}\n"
                "Herhaalde identieke fouten worden onderdrukt."
            ),
            opener=opener,
        )

    def recovered(self, token: str, *, now: datetime, opener=urlopen) -> None:
        if self._active is None:
            return
        active = self._active
        self._active = None
        duration = now - active.first_seen
        self._publish(
            token,
            title="PicoT integratiefout hersteld",
            message=(
                f"De integratiefout is hersteld.\n\n"
                f"Eerste fout: {active.first_seen.isoformat()}\n"
                f"Hersteld: {now.isoformat()}\n"
                f"Duur: {duration}\n"
                f"Aantal gedetecteerde fouten: {active.count}"
            ),
            opener=opener,
        )

    @staticmethod
    def _publish(token: str, *, title: str, message: str, opener=urlopen) -> None:
        endpoint = "/api/services/persistent_notification/create"
        payload = {
            "title": title,
            "message": message,
            "notification_id": NOTIFICATION_ID,
        }
        request = Request(
            f"{SUPERVISOR_BASE_URL}{endpoint}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
        status = getattr(response, "status", None)
        if not isinstance(status, int) or status not in {200, 201}:
            raise RuntimeError(
                f"HA notification publish failed endpoint={endpoint} http_status={status}"
            )
