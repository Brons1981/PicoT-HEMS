from __future__ import annotations

from datetime import UTC, datetime

import pytest

from picot.adapters.home_assistant_household_state import (
    household_state_from_grid_power_entity,
)


def _state(value: str) -> dict[str, object]:
    return {
        "entity_id": "sensor.shellypro3em_5c013b04bb78_vermogen",
        "state": value,
        "last_updated": "2026-08-02T10:00:00+00:00",
        "attributes": {"unit_of_measurement": "W"},
    }


def test_normalizes_positive_import_power() -> None:
    result = household_state_from_grid_power_entity(_state("842.5"))

    assert result.grid_power_w == 842.5
    assert result.measured_at == datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
    assert result.phases == ()


def test_preserves_negative_export_power() -> None:
    result = household_state_from_grid_power_entity(_state("-1275"))

    assert result.grid_power_w == -1275.0


def test_can_invert_source_direction() -> None:
    result = household_state_from_grid_power_entity(
        _state("1275"),
        import_is_positive=False,
    )

    assert result.grid_power_w == -1275.0


def test_rejects_unavailable_state() -> None:
    with pytest.raises(ValueError, match="unavailable"):
        household_state_from_grid_power_entity(_state("unavailable"))


def test_rejects_non_watt_entity() -> None:
    state = _state("100")
    state["attributes"] = {"unit_of_measurement": "kW"}

    with pytest.raises(ValueError, match="watts"):
        household_state_from_grid_power_entity(state)
