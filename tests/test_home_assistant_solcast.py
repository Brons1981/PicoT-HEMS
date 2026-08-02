from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from picot.adapters.home_assistant_solcast import (
    SolcastSnapshotError,
    solcast_snapshot_from_entities,
)

OBSERVED_AT = datetime(2026, 8, 2, 18, 30, tzinfo=UTC)


def _state(value: object, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"state": value, "attributes": attributes or {}}


def _states() -> dict[str, dict[str, Any]]:
    today_points = [
        {
            "period_start": "2026-08-02T12:00:00+02:00",
            "pv_estimate": 2.9,
            "pv_estimate10": 2.4,
            "pv_estimate90": 3.0,
        }
    ]
    tomorrow_points = [
        {
            "period_start": "2026-08-03T12:00:00+02:00",
            "pv_estimate": 2.7,
            "pv_estimate10": 1.9,
            "pv_estimate90": 2.8,
        }
    ]
    return {
        "sensor.solcast_pv_forecast_voorspelling_vandaag": _state(
            "25.7471",
            {
                "estimate10": 22.3047,
                "estimate90": 26.5649,
                "analysis": {"confidence": 0.8396},
                "detailedForecast": today_points,
            },
        ),
        "sensor.solcast_pv_forecast_voorspelling_morgen": _state(
            "23.7034",
            {
                "estimate10": 15.7293,
                "estimate90": 25.4288,
                "analysis": {"confidence": 0.6186},
                "detailedForecast": tomorrow_points,
            },
        ),
        "sensor.solcast_pv_forecast_resterende_voorspelling_vandaag": _state(
            "1.5311"
        ),
        "sensor.solcast_pv_forecast_huidig_vermogen": _state("933"),
        "sensor.solcast_pv_forecast_api_laatst_geraadpleegd": _state(
            "2026-08-02T16:23:59+00:00"
        ),
        "sensor.solcast_pv_forecast_api_gebruik": _state("10"),
        "sensor.solcast_pv_forecast_api_limiet": _state("10"),
    }


def test_solcast_snapshot_normalizes_totals_confidence_and_intervals() -> None:
    snapshot = solcast_snapshot_from_entities(_states(), observed_at=OBSERVED_AT)

    assert snapshot.status == "available"
    assert snapshot.forecast_today_kwh == 25.7471
    assert snapshot.forecast_tomorrow_kwh == 23.7034
    assert snapshot.remaining_today_kwh == 1.5311
    assert snapshot.current_expected_power_w == 933.0
    assert snapshot.today_confidence == 0.8396
    assert snapshot.tomorrow_confidence == 0.6186
    assert snapshot.api_used == 10
    assert snapshot.api_limit == 10
    assert len(snapshot.forecast_points) == 2
    assert snapshot.forecast_points[0].estimate_kw == 2.9
    assert snapshot.forecast_points[1].estimate10_kw == 1.9


def test_solcast_snapshot_rejects_unavailable_required_entity() -> None:
    states = _states()
    states["sensor.solcast_pv_forecast_huidig_vermogen"]["state"] = "unavailable"

    with pytest.raises(SolcastSnapshotError, match="unavailable"):
        solcast_snapshot_from_entities(states, observed_at=OBSERVED_AT)


def test_solcast_snapshot_requires_timezone_aware_observation_time() -> None:
    with pytest.raises(SolcastSnapshotError, match="timezone-aware"):
        solcast_snapshot_from_entities(
            _states(),
            observed_at=datetime(2026, 8, 2, 18, 30),
        )
