import json
from datetime import date, datetime
from urllib.error import URLError
from zoneinfo import ZoneInfo

from picot.v2 import pv_sunset_source

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def test_home_assistant_sun_exposes_one_traceable_next_setting(
    monkeypatch: object,
) -> None:
    requested: list[object] = []
    payload = {
        "entity_id": "sun.sun",
        "state": "above_horizon",
        "last_updated": "2026-08-16T12:00:00+00:00",
        "attributes": {
            "next_setting": "2026-08-16T18:55:00+00:00",
        },
    }

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

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_sunset_source,
        "urlopen",
        fake_urlopen,
    )

    result = pv_sunset_source.HomeAssistantSunsetReader(
        "supervisor-token"
    ).read(local_timezone=AMSTERDAM)

    assert len(requested) == 1
    request = requested[0]
    assert request.full_url == (  # type: ignore[attr-defined]
        "http://supervisor/core/api/states/sun.sun"
    )
    assert request.get_header("Authorization") == (  # type: ignore[attr-defined]
        "Bearer supervisor-token"
    )
    assert result.source_entity_id == "sun.sun"
    assert result.status == "available"
    assert result.error is None
    assert result.source_updated_at == datetime.fromisoformat(
        "2026-08-16T12:00:00+00:00"
    )
    assert result.sunsets_by_local_date == (
        (
            date(2026, 8, 16),
            datetime(
                2026,
                8,
                16,
                20,
                55,
                tzinfo=AMSTERDAM,
            ),
        ),
    )
    assert result.method_version == "home-assistant-sun-next-setting:v1"


def test_home_assistant_sun_does_not_invent_later_horizon_days(
    monkeypatch: object,
) -> None:
    payload = {
        "entity_id": "sun.sun",
        "last_updated": "2026-08-16T12:00:00+00:00",
        "attributes": {
            "next_setting": "2026-08-16T18:55:00+00:00",
        },
    }

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

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_sunset_source,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = pv_sunset_source.HomeAssistantSunsetReader("token").read(
        local_timezone=AMSTERDAM
    )

    assert tuple(day for day, _ in result.sunsets_by_local_date) == (
        date(2026, 8, 16),
    )


def test_home_assistant_sun_failure_is_explicit(
    monkeypatch: object,
) -> None:
    def failing_urlopen(request: object, timeout: int) -> object:
        del request, timeout
        raise URLError("sun unavailable")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_sunset_source,
        "urlopen",
        failing_urlopen,
    )

    result = pv_sunset_source.HomeAssistantSunsetReader("token").read(
        local_timezone=AMSTERDAM
    )

    assert result.status == "unavailable"
    assert result.error == "URLError"
    assert result.sunsets_by_local_date == ()
    assert result.source_updated_at is None


def test_home_assistant_sun_missing_next_setting_is_explicit(
    monkeypatch: object,
) -> None:
    payload = {
        "entity_id": "sun.sun",
        "last_updated": "2026-08-16T12:00:00+00:00",
        "attributes": {},
    }

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

    monkeypatch.setattr(  # type: ignore[attr-defined]
        pv_sunset_source,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )

    result = pv_sunset_source.HomeAssistantSunsetReader("token").read(
        local_timezone=AMSTERDAM
    )

    assert result.status == "unavailable"
    assert result.error == "next_setting_missing"
    assert result.sunsets_by_local_date == ()
