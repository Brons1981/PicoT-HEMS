import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from picot.v2 import power_history
from picot.v2.power_history import (
    PowerHistoryCache,
    PowerHistoryPoint,
    PowerHistorySeries,
    PowerHistorySnapshot,
    PowerSeriesSpec,
)

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
    assert all(item.history_semantics == "state_hold" for item in result.series)
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


def test_series_rejects_unknown_history_semantics() -> None:
    try:
        PowerHistorySeries(
            series_id="pv",
            role="pv_generation",
            source_entity_id=PV,
            transform="identity",
            points=(),
            history_semantics="smoothed",
        )
    except ValueError as exc:
        assert str(exc) == "unsupported power history semantics"
    else:
        raise AssertionError("unsupported history semantics were accepted")


def test_cache_reads_only_new_tail_and_deduplicates_boundary() -> None:
    first_end = START + timedelta(hours=8)
    second_end = first_end + timedelta(minutes=1)
    boundary = PowerHistoryPoint(first_end, 800.0, "evidence-boundary")
    new_point = PowerHistoryPoint(second_end, 900.0, "evidence-new")

    class FakeReader:
        def __init__(self) -> None:
            self.windows: list[tuple[datetime, datetime]] = []

        def read(
            self,
            *,
            specs: tuple[PowerSeriesSpec, ...],
            starts_at: datetime,
            ends_at: datetime,
        ) -> PowerHistorySnapshot:
            self.windows.append((starts_at, ends_at))
            points = (
                (boundary,)
                if len(self.windows) == 1
                else (boundary, new_point)
            )
            return PowerHistorySnapshot(
                starts_at=starts_at,
                ends_at=ends_at,
                status="available",
                error=None,
                series=(PowerHistorySeries(
                    series_id=specs[0].series_id,
                    role=specs[0].role,
                    source_entity_id=specs[0].entity_id,
                    transform=specs[0].transform,
                    points=points,
                ),),
            )

    reader = FakeReader()
    cache = PowerHistoryCache()
    specs = (PowerSeriesSpec("pv", "pv_generation", PV),)

    cache.update(  # type: ignore[arg-type]
        reader,
        specs=specs,
        starts_at=START,
        ends_at=first_end,
    )
    result = cache.update(  # type: ignore[arg-type]
        reader,
        specs=specs,
        starts_at=START,
        ends_at=second_end,
    )

    assert reader.windows == [(START, first_end), (first_end, second_end)]
    assert result.starts_at == START
    assert result.ends_at == second_end
    assert result.series[0].points == (boundary, new_point)


def test_cache_keeps_proven_points_when_incremental_read_fails() -> None:
    first_end = START + timedelta(hours=8)
    second_end = first_end + timedelta(minutes=1)
    proven = PowerHistoryPoint(first_end, 800.0, "evidence-proven")

    class FakeReader:
        def __init__(self) -> None:
            self.call_count = 0

        def read(
            self,
            *,
            specs: tuple[PowerSeriesSpec, ...],
            starts_at: datetime,
            ends_at: datetime,
        ) -> PowerHistorySnapshot:
            self.call_count += 1
            if self.call_count == 2:
                return PowerHistorySnapshot(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status="unavailable",
                    error="TimeoutError",
                    series=(),
                )
            return PowerHistorySnapshot(
                starts_at=starts_at,
                ends_at=ends_at,
                status="available",
                error=None,
                series=(PowerHistorySeries(
                    series_id=specs[0].series_id,
                    role=specs[0].role,
                    source_entity_id=specs[0].entity_id,
                    transform=specs[0].transform,
                    points=(proven,),
                ),),
            )

    reader = FakeReader()
    cache = PowerHistoryCache()
    specs = (PowerSeriesSpec("pv", "pv_generation", PV),)
    cache.update(  # type: ignore[arg-type]
        reader,
        specs=specs,
        starts_at=START,
        ends_at=first_end,
    )

    result = cache.update(  # type: ignore[arg-type]
        reader,
        specs=specs,
        starts_at=START,
        ends_at=second_end,
    )

    assert result.status == "available"
    assert result.error == "TimeoutError"
    assert result.ends_at == first_end
    assert result.series[0].points == (proven,)
