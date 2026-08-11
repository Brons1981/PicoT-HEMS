from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from picot.addon.runtime_notifications import RuntimeFailureNotifier


class Response:
    status = 200


def test_notifier_suppresses_identical_repeats_and_announces_recovery() -> None:
    calls: list[dict[str, Any]] = []

    def opener(request: Any, timeout: float) -> Response:
        assert timeout > 0
        calls.append(json.loads(request.data.decode("utf-8")))
        return Response()

    notifier = RuntimeFailureNotifier()
    now = datetime(2026, 8, 11, 12, 32, tzinfo=timezone.utc)

    notifier.failure(
        "token",
        now=now,
        fingerprint="DiagnosticsPublishError:sensor.example:400",
        message="entity_id=sensor.example endpoint=/api/states/sensor.example http_status=400",
        opener=opener,
    )
    notifier.failure(
        "token",
        now=now,
        fingerprint="DiagnosticsPublishError:sensor.example:400",
        message="same",
        opener=opener,
    )
    notifier.recovered("token", now=now, opener=opener)

    assert len(calls) == 2
    assert calls[0]["notification_id"] == "picot_runtime_integration_error"
    assert "integratiefout" in calls[0]["title"]
    assert "hersteld" in calls[1]["title"]
    assert "Aantal gedetecteerde fouten: 2" in calls[1]["message"]
