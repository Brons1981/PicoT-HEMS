from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.current_storage_state import CurrentStorageState


def _state(**overrides: object) -> CurrentStorageState:
    values: dict[str, object] = {
        "storage_state_id": "storage-state-1",
        "execution_scope_id": "battery-1",
        "capability_id": "storage-capability-1",
        "current_soc": 0.55,
        "usable_capacity_wh": 8000.0,
        "measured_at": datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        "confidence": 0.98,
        "evidence_ids": ("sensor:battery_soc", "config:usable_capacity"),
    }
    values.update(overrides)
    return CurrentStorageState(**values)  # type: ignore[arg-type]


def test_current_stored_energy_is_canonical_soc_times_usable_capacity() -> None:
    state = _state(current_soc=0.55, usable_capacity_wh=8000.0)

    assert state.current_stored_energy_wh == pytest.approx(4400.0)


def test_current_storage_state_is_immutable() -> None:
    state = _state()

    with pytest.raises(FrozenInstanceError):
        state.current_soc = 0.75  # type: ignore[misc]


@pytest.mark.parametrize("current_soc", [-0.01, 1.01])
def test_current_storage_state_rejects_soc_outside_normalized_range(
    current_soc: float,
) -> None:
    with pytest.raises(ValueError, match="SoC"):
        _state(current_soc=current_soc)


def test_current_storage_state_rejects_non_positive_usable_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        _state(usable_capacity_wh=0.0)


def test_current_storage_state_rejects_naive_measurement_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _state(measured_at=datetime(2026, 8, 12, 8, 0))


def test_current_storage_state_rejects_confidence_outside_range() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _state(confidence=1.01)


def test_current_storage_state_accepts_older_measurement_for_snapshot_validation() -> None:
    state = _state(measured_at=datetime.now(UTC) - timedelta(minutes=5))

    assert state.measured_at < datetime.now(UTC)
