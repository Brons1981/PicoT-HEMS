import json
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

import pytest

from picot.v2.pv_solar_history import (
    SOLAR_HISTORY_METHOD_VERSION,
    HomeAssistantSolarHistoryReader,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
STARTS_AT = datetime(2026, 8, 16, 17, 0, tzinfo=UTC)
ENDS_AT = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)


def test_home_assistant_solar_history_preserves_bounded_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[object] = []
    payload = [
        [
            {
                "entity_id": "sun.sun",
                "last_updated": "2026-08-16T17:45:00+00:00",
                "attributes": {
                    "azimuth": 274.5,
                    "elevation": 4.25,
                    "next_setting": "2026-08-16T18:55:00+00:00",
                },
            },
            {
                "entity_id": "sun.sun",
                "last_updated": "2026-08-16T17:15:00+00:00",
                "attributes": {
                    "azimuth": 268.0,
                    "elevation": 8.5,
                    "next_setting": "2026-08-16T18:55:00+00:00",
                },
            },
        ]
    ]

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
        requested.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        "picot.v2.pv_solar_history.urlopen",
        fake_urlopen,
    )

    result = HomeAssistantSolarHistoryReader(
        "supervisor-token"
    ).read(
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        local_timezone=AMSTERDAM,
    )

    assert len(requested) == 1
    request = requested[0]
    parsed = urlparse(request.full_url)  # type: ignore[attr-defined]
    assert unquote(parsed.path).endswith(
        f"/history/period/{STARTS_AT.isoformat()}"
    )
    query = parse_qs(parsed.query)
    assert query["filter_entity_id"] == ["sun.sun"]
    assert query["end_time"] == [ENDS_AT.isoformat()]
    assert "no_attributes" not in query
    assert request.get_header("Authorization") == (  # type: ignore[attr-defined]
        "Bearer supervisor-token"
    )

    assert result.source_entity_id == "sun.sun"
    assert result.starts_at == STARTS_AT
    assert result.ends_at == ENDS_AT
    assert result.status == "available"
    assert result.error is None
    assert result.method_version == SOLAR_HISTORY_METHOD_VERSION
    assert result.method_version == (
        "home-assistant-sun-history-attributes:v1"
    )

    assert len(result.observations) == 2
    first, second = result.observations
    assert first.sampled_at == datetime(
        2026, 8, 16, 17, 15, tzinfo=UTC
    )
    assert first.solar_azimuth_degrees == 268.0
    assert first.solar_elevation_degrees == 8.5
    assert first.sunset_at == datetime(
        2026,
        8,
        16,
        20,
        55,
        tzinfo=AMSTERDAM,
    )
    assert first.evidence_id.startswith("evidence-solar-history-")
    assert second.sampled_at == datetime(
        2026, 8, 16, 17, 45, tzinfo=UTC
    )
    assert second.evidence_id != first.evidence_id


def test_invalid_or_incomplete_solar_attributes_are_explicitly_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = [
        [
            {
                "entity_id": "sun.sun",
                "last_updated": "2026-08-16T17:15:00+00:00",
                "attributes": {
                    "azimuth": 268.0,
                    "next_setting": "2026-08-16T18:55:00+00:00",
                },
            },
            {
                "entity_id": "sun.sun",
                "last_updated": "2026-08-16T17:45:00+00:00",
                "attributes": {
                    "azimuth": "unknown",
                    "elevation": 4.25,
                    "next_setting": "not-a-time",
                },
            },
        ]
    ]

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

    monkeypatch.setattr(
        "picot.v2.pv_solar_history.urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = HomeAssistantSolarHistoryReader("token").read(
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        local_timezone=AMSTERDAM,
    )

    assert result.status == "empty"
    assert result.error == "no_valid_solar_observations"
    assert result.observations == ()


def test_solar_history_source_failure_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_urlopen(request: object, timeout: int) -> object:
        del request, timeout
        raise URLError("sun history unavailable")

    monkeypatch.setattr(
        "picot.v2.pv_solar_history.urlopen",
        failing_urlopen,
    )

    result = HomeAssistantSolarHistoryReader("token").read(
        starts_at=STARTS_AT,
        ends_at=ENDS_AT,
        local_timezone=AMSTERDAM,
    )

    assert result.status == "unavailable"
    assert result.error == "URLError"
    assert result.observations == ()


@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    (
        (datetime(2026, 8, 16, 17, 0), ENDS_AT),
        (STARTS_AT, datetime(2026, 8, 16, 18, 0)),
    ),
)
def test_solar_history_bounds_require_timezone_awareness(
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    reader = HomeAssistantSolarHistoryReader("token")

    with pytest.raises(ValueError, match="timezone-aware"):
        reader.read(
            starts_at=starts_at,
            ends_at=ends_at,
            local_timezone=AMSTERDAM,
        )
