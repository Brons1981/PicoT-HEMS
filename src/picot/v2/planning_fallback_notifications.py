"""Deduplicated Home Assistant notices for canonical planning fallback."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.request import Request, urlopen

from picot.v2.contracts import CanonicalPipelineRun

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0
NOTIFICATION_ID = "picot_planning_fallback"


@dataclass(slots=True)
class PlanningFallbackNotifier:
    """Notify once per fallback cause and once when planning recovers."""

    _active_fingerprint: str | None = None

    def update(
        self,
        token: str,
        *,
        run: CanonicalPipelineRun,
        now: datetime,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        if run.evaluation.status == "fallback_active":
            fingerprint = ":".join(
                (
                    run.evaluation.reason,
                    run.candidate_set.derivation_status,
                    run.candidate_set.derivation_reason or "none",
                )
            )
            if fingerprint == self._active_fingerprint:
                return
            self._active_fingerprint = fingerprint
            current_mode = run.primitive_boundary.planned_vendor_mode or "niet beschikbaar"
            self._publish(
                token,
                title="PicoT aandacht vereist: geen uitvoerbaar plan",
                message=(
                    "PicoT heeft geen kandidaat met een berekende outcome. "
                    f"De veilige terugvalmodus '{current_mode}' blijft actief.\n\n"
                    f"Oorzaak: {run.evaluation.reason}\n"
                    f"Kandidaatafleiding: {run.candidate_set.derivation_status}\n"
                    f"Detail: {run.candidate_set.derivation_reason or 'geen'}\n"
                    f"Vastgesteld: {now.isoformat()}\n"
                    f"Run: {run.planning_input.run_id}\n"
                    "Een identieke oorzaak wordt niet opnieuw gemeld."
                ),
                opener=opener,
            )
            return

        if self._active_fingerprint is None:
            return
        self._active_fingerprint = None
        self._publish(
            token,
            title="PicoT planning hersteld",
            message=(
                "PicoT heeft opnieuw een inhoudelijk berekend plan beschikbaar.\n\n"
                f"Hersteld: {now.isoformat()}\n"
                f"Run: {run.planning_input.run_id}"
            ),
            opener=opener,
        )

    @staticmethod
    def _publish(
        token: str,
        *,
        title: str,
        message: str,
        opener: Callable[..., object],
    ) -> None:
        endpoint = "/api/services/persistent_notification/create"
        request = Request(
            f"{SUPERVISOR_BASE_URL}{endpoint}",
            data=json.dumps(
                {
                    "title": title,
                    "message": message,
                    "notification_id": NOTIFICATION_ID,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
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
                "HA planning fallback notification failed "
                f"endpoint={endpoint} http_status={status}"
            )
