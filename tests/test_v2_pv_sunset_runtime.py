from datetime import date, datetime
from zoneinfo import ZoneInfo

from picot.v2.projection import Card, Projection
from picot.v2.pv_sunset_runtime import (
    attach_pv_sunset_runtime_diagnostics,
)
from picot.v2.pv_sunset_source import SunsetReadResult

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SOURCE_UPDATED_AT = datetime.fromisoformat(
    "2026-08-16T12:00:00+00:00"
)
SUNSET_AT = datetime(
    2026,
    8,
    16,
    20,
    55,
    tzinfo=AMSTERDAM,
)


def _projection() -> Projection:
    return Projection(
        cards=(
            Card(
                entity_id="sensor.picot_v2_pipeline_01_planning_input",
                state="ready",
                attributes={"existing": "preserved"},
            ),
            Card(
                entity_id="sensor.picot_v2_pipeline_02_opportunity_engine",
                state="ready",
                attributes={"untouched": True},
            ),
        ),
        projection_ms=1.25,
    )


def test_available_sunset_source_is_visible_without_recalculation() -> None:
    source = SunsetReadResult(
        source_entity_id="sun.sun",
        status="available",
        error=None,
        source_updated_at=SOURCE_UPDATED_AT,
        sunsets_by_local_date=((date(2026, 8, 16), SUNSET_AT),),
        method_version="home-assistant-sun-next-setting:v1",
    )
    offsets = {
        "forecast-1830": -10.0,
        "forecast-1900": 20.0,
    }

    enriched = attach_pv_sunset_runtime_diagnostics(
        _projection(),
        source=source,
        local_timezone="Europe/Amsterdam",
        offsets_by_interval_id=offsets,
    )

    attributes = enriched.cards[0].attributes
    assert attributes["existing"] == "preserved"
    assert attributes["pv_sunset_source_status"] == "available"
    assert attributes["pv_sunset_source_entity_id"] == "sun.sun"
    assert attributes["pv_sunset_source_error"] is None
    assert attributes["pv_sunset_source_updated_at"] == (
        SOURCE_UPDATED_AT.isoformat()
    )
    assert attributes["pv_sunset_source_method_version"] == (
        "home-assistant-sun-next-setting:v1"
    )
    assert attributes["pv_sunset_local_timezone"] == "Europe/Amsterdam"
    assert attributes["pv_sunset_date_count"] == 1
    assert attributes["pv_sunset_dates"] == ["2026-08-16"]
    assert attributes["pv_sunset_values"] == [
        {
            "local_date": "2026-08-16",
            "sunset_at": SUNSET_AT.isoformat(),
        }
    ]
    assert attributes["pv_sunset_offset_interval_count"] == 2
    assert attributes["pv_sunset_offset_method_version"] == (
        "pv-sunset-offset:interval-midpoint:v1"
    )
    assert enriched.cards[1].attributes == {"untouched": True}
    assert enriched.projection_ms == 1.25


def test_unavailable_sunset_source_remains_explicit() -> None:
    source = SunsetReadResult(
        source_entity_id="sun.sun",
        status="unavailable",
        error="URLError",
        source_updated_at=None,
        sunsets_by_local_date=(),
        method_version="home-assistant-sun-next-setting:v1",
    )

    enriched = attach_pv_sunset_runtime_diagnostics(
        _projection(),
        source=source,
        local_timezone="Europe/Amsterdam",
        offsets_by_interval_id={},
    )

    attributes = enriched.cards[0].attributes
    assert attributes["pv_sunset_source_status"] == "unavailable"
    assert attributes["pv_sunset_source_error"] == "URLError"
    assert attributes["pv_sunset_source_updated_at"] is None
    assert attributes["pv_sunset_date_count"] == 0
    assert attributes["pv_sunset_dates"] == []
    assert attributes["pv_sunset_values"] == []
    assert attributes["pv_sunset_offset_interval_count"] == 0
