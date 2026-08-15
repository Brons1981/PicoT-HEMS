import json
from datetime import UTC, datetime, timedelta
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from picot.v2 import pv_actual_history
from picot.v2.pv_actual_intervals import build_actual_pv_interval


BASE = datetime(2026, 8, 15, 8, 30, tzinfo=UTC)
END = BASE + timedelta(minutes=30)
LOOKUP_START = BASE - timedelta(seconds=5)
ENTITY_ID = "sensor.inverter_54200dsn211r0265_vermogen"


def test_home_assistant_goodwe_history_becomes_actual_pv_interval(
    monkeypatch: object,
) -> None:
    payload = [[
        {
            "entity_id": ENTITY_ID,
            "state": "600",
            "last_updated": "2026-08-15T08:29:55+00:00",
        },
        {
            "entity_id": ENTITY_ID,
            "state": "900",
            "last_updated": "2026-08-15T08:40:00+00:00",
        },
        {
            "entity_id": ENTITY_ID,
            "state": "300",
            "last_updated": "2026-08-15T08:50:00+00:00",
        },
        {
            "entity_id": ENTITY_ID,
            "state": "600",
            "last_updated": "2026-08-15T09:00:00+00:00",
        },
    ]]
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        assert timeout == 5
        requested_urls.append(request.full_url)  # type: ignore[attr-defined]
        return FakeResponse()

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_actual_history,
        "urlopen",
        fake_urlopen,
    )

    result = pv_actual_history.HomeAssistantPVHistoryReader(
        "token"
    ).read(
        entity_id=ENTITY_ID,
        starts_at=LOOKUP_START,
        ends_at=END,
    )

    assert result.status == "available"
    assert result.error is None
    assert result.entity_id == ENTITY_ID
    assert result.starts_at == LOOKUP_START
    assert result.ends_at == END
    assert len(result.observations) == 4
    assert [item.power_w for item in result.observations] == [
        600.0,
        900.0,
        300.0,
        600.0,
    ]
    assert [item.sampled_at for item in result.observations] == [
        LOOKUP_START,
        BASE + timedelta(minutes=10),
        BASE + timedelta(minutes=20),
        END,
    ]
    assert len({
        item.evidence_id
        for item in result.observations
    }) == 4

    parsed_url = urlparse(requested_urls[0])
    assert unquote(parsed_url.path).endswith(
        f"/api/history/period/{LOOKUP_START.isoformat()}"
    )
    assert parse_qs(parsed_url.query) == {
        "filter_entity_id": [ENTITY_ID],
        "end_time": [END.isoformat()],
        "minimal_response": ["0"],
        "no_attributes": ["1"],
        "significant_changes_only": ["0"],
    }

    interval = build_actual_pv_interval(
        interval_id="pv-actual-2026-08-15T08:30Z",
        starts_at=BASE,
        ends_at=END,
        captured_at=END + timedelta(minutes=5),
        observations=result.observations,
        telemetry_interval_seconds=300,
    )

    assert interval is not None
    assert interval.pv_energy_wh == pytest.approx(300.0)
    assert interval.evidence_type == "ACTUAL"
    assert interval.actual_evidence_ids == tuple(
        item.evidence_id
        for item in result.observations
    )


def test_goodwe_history_failure_is_explicit(
    monkeypatch: object,
) -> None:
    def failing_urlopen(request: object, timeout: int) -> object:
        del request, timeout
        raise URLError("history unavailable")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_actual_history,
        "urlopen",
        failing_urlopen,
    )

    result = pv_actual_history.HomeAssistantPVHistoryReader(
        "token"
    ).read(
        entity_id=ENTITY_ID,
        starts_at=LOOKUP_START,
        ends_at=END,
    )

    assert result.status == "unavailable"
    assert result.error == "URLError"
    assert result.observations == ()
