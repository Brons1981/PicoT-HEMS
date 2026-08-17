import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from picot.v2 import power_history
from picot.v2.power_history import PowerSeriesSpec

START = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
END = START + timedelta(hours=12)
P1 = "sensor.p1_power"
PV = "sensor.pv_power"


def test_reader_builds_canonical_directional_series_in_one_request(
    monkeypatch: object,
) -> None:
    payload = [
        [
            {
                "entity_id": P1,
                "state": "250",
                "last_updated": "2026-08-17T08:00:00+00:00",
            },
            {
                "entity_id": P1,
                "state": "-800",
                "last_updated": "2026-08-17T08:01:00+00:00",
            },
        ],
        [
            {
                "entity_id": PV,
                "state": "1200",
                "last_updated": "2026-08-17T08:00:00+00:00",
            }
        ],
    ]
    requested_urls: list[str] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        assert timeout == 5
        requested_urls.append(request.full_url)  # type: ignore[attr-defined]
        return FakeResponse()

    monkeypatch.setattr(power_history, "urlopen", fake_urlopen)  # type: ignore[attr-defined]
    result = power_history.HomeAssistantPowerHistoryReader("token").read(
        specs=(
            PowerSeriesSpec("pv", "pv_generation", PV),
            PowerSeriesSpec("import", "grid_import", P1, "positive"),
            PowerSeriesSpec(
                "export",
                "grid_export",
                P1,
                "negative_magnitude",
            ),
        ),
        starts_at=START,
        ends_at=END,
    )

    assert result.status == "available"
    assert result.error is None
    assert [item.role for item in result.series] == [
        "pv_generation",
        "grid_import",
        "grid_export",
    ]
    assert [point.power_w for point in result.series[0].points] == [1200.0]
    assert [point.power_w for point in result.series[1].points] == [250.0, 0.0]
    assert [point.power_w for point in result.series[2].points] == [0.0, 800.0]
    assert all(
        point.evidence_id.startswith("evidence-power-history-")
        for series in result.series
        for point in series.points
    )

    parsed = urlparse(requested_urls[0])
    assert unquote(parsed.path).endswith(
        f"/api/history/period/{START.isoformat()}"
    )
    assert parse_qs(parsed.query) == {
        "filter_entity_id": [f"{PV},{P1}"],
        "end_time": [END.isoformat()],
        "no_attributes": ["1"],
    }


def test_reader_drops_unknown_invalid_and_out_of_range_samples(
    monkeypatch: object,
) -> None:
    payload = [[
        {
            "entity_id": PV,
            "state": "unknown",
            "last_updated": "2026-08-17T08:00:00+00:00",
        },
        {
            "entity_id": PV,
            "state": "nan",
            "last_updated": "2026-08-17T08:01:00+00:00",
        },
        {
            "entity_id": PV,
            "state": "900",
            "last_updated": "2026-08-16T23:59:00+00:00",
        },
    ]]

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        power_history,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )
    result = power_history.HomeAssistantPowerHistoryReader("token").read(
        specs=(PowerSeriesSpec("pv", "pv_generation", PV),),
        starts_at=START,
        ends_at=END,
    )

    assert result.status == "empty"
    assert result.series[0].points == ()


def test_spec_rejects_implicit_or_unknown_transform() -> None:
    try:
        PowerSeriesSpec("pv", "pv_generation", PV, "absolute")
    except ValueError as exc:
        assert str(exc) == "unsupported power history transform"
    else:
        raise AssertionError("unsupported transform was accepted")
