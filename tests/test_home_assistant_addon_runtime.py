from __future__ import annotations

from datetime import UTC, datetime

from picot.addon.runtime import _desired_option, _price_forecast
from picot.domain.execution_primitive import ExecutionPrimitive

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def test_addon_maps_only_the_two_accepted_live_modes() -> None:
    assert (
        _desired_option(ExecutionPrimitive.BALANCE_DISCHARGE_ONLY)
        == "Alleen slim ontladen"
    )
    assert (
        _desired_option(ExecutionPrimitive.BALANCE_BIDIRECTIONAL)
        == "Nul op de meter"
    )


def test_addon_builds_price_forecast_from_nordpool_raw_points() -> None:
    state = {
        "entity_id": "sensor.nordpool_kwh_nl_eur_2_10_021",
        "attributes": {
            "raw_today": [
                {
                    "start": "2026-08-02T09:00:00+00:00",
                    "end": "2026-08-02T10:00:00+00:00",
                    "value": 0.21,
                },
                {
                    "start": "2026-08-02T10:00:00+00:00",
                    "end": "2026-08-02T11:00:00+00:00",
                    "value": 0.11,
                },
            ],
            "raw_tomorrow": [],
        },
    }

    forecast = _price_forecast(state, now=NOW)

    assert forecast.source == "sensor.nordpool_kwh_nl_eur_2_10_021"
    assert tuple(point.value for point in forecast.points) == (0.21, 0.11)
    assert forecast.expires_at == datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
