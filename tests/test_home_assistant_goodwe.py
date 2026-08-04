from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from picot.adapters.home_assistant_goodwe import (
    GoodWeSnapshotError,
    goodwe_snapshot_from_entities,
)

OBSERVED_AT = datetime(2026, 8, 2, 19, 30, tzinfo=UTC)


def _state(value: object) -> dict[str, Any]:
    return {"state": value, "attributes": {}}


def _goodwe_states() -> dict[str, dict[str, Any]]:
    return {
        "sensor.inverter_54200dsn211r0265_vermogen": _state(273.0),
        "sensor.inverter_54200dsn211r0265_energy_today": _state(26.7),
        "sensor.inverter_54200dsn211r0265_energie": _state(23349.1),
        "sensor.inverter_54200dsn211r0265_temperatuur": _state(35.0),
    }


def test_goodwe_snapshot_normalizes_selected_read_only_fields() -> None:
    snapshot = goodwe_snapshot_from_entities(
        _goodwe_states(),
        observed_at=OBSERVED_AT,
    )

    assert snapshot.status == "available"
    assert snapshot.source == "Home Assistant GoodWe SEMS API"
    assert snapshot.observed_at == OBSERVED_AT
    assert snapshot.solar_power_w == 273.0
    assert snapshot.generation_today_kwh == 26.7
    assert snapshot.generation_total_kwh == 23349.1
    assert snapshot.temperature_c == 35.0


def test_goodwe_snapshot_rejects_unavailable_required_entity() -> None:
    states = _goodwe_states()
    states["sensor.inverter_54200dsn211r0265_vermogen"] = _state("unavailable")

    with pytest.raises(GoodWeSnapshotError, match="GoodWe entity is unavailable"):
        goodwe_snapshot_from_entities(states, observed_at=OBSERVED_AT)


def test_goodwe_snapshot_rejects_non_numeric_value() -> None:
    states = _goodwe_states()
    states["sensor.inverter_54200dsn211r0265_temperatuur"] = _state("invalid")

    with pytest.raises(GoodWeSnapshotError, match="temperature_c is not numeric"):
        goodwe_snapshot_from_entities(states, observed_at=OBSERVED_AT)


def test_goodwe_snapshot_requires_timezone_aware_observation() -> None:
    with pytest.raises(GoodWeSnapshotError, match="timezone-aware"):
        goodwe_snapshot_from_entities(
            _goodwe_states(),
            observed_at=datetime(2026, 8, 2, 19, 30),
        )
