from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from picot.v2.contracts import CurrentStorageState


def test_current_storage_state_is_immutable_and_traceable() -> None:
    state = CurrentStorageState(
        storage_state_id="storage-state-home-battery",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.40,
        usable_capacity_wh=8160.0,
        measured_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        confidence=0.95,
        evidence_ids=(
            "ha:zendure-soc",
            "config:usable-capacity",
        ),
    )

    assert state.current_stored_energy_wh == pytest.approx(3264.0)
    assert state.execution_scope_id == "home-battery"
    assert state.capability_id == "storage-capability-home-battery"
    assert state.evidence_ids == (
        "ha:zendure-soc",
        "config:usable-capacity",
    )

    with pytest.raises(FrozenInstanceError):
        state.current_soc = 0.50  # type: ignore[misc]


def test_current_stored_energy_uses_the_canonical_adr038_formula() -> None:
    assert CurrentStorageState(
        storage_state_id="storage-state-1",
        execution_scope_id="battery-1",
        capability_id="capability-1",
        current_soc=0.625,
        usable_capacity_wh=8000.0,
        measured_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        confidence=1.0,
        evidence_ids=("measurement:1",),
    ).current_stored_energy_wh == pytest.approx(5000.0)


@pytest.mark.parametrize(
    ("current_soc", "usable_capacity_wh", "message"),
    (
        (-0.01, 8000.0, "current_soc must be between 0.0 and 1.0"),
        (1.01, 8000.0, "current_soc must be between 0.0 and 1.0"),
        (0.50, 0.0, "usable_capacity_wh must be positive"),
        (0.50, -1.0, "usable_capacity_wh must be positive"),
    ),
)
def test_current_storage_state_rejects_invalid_energy_boundaries(
    current_soc: float,
    usable_capacity_wh: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        CurrentStorageState(
            storage_state_id="storage-state-invalid",
            execution_scope_id="battery-invalid",
            capability_id="capability-invalid",
            current_soc=current_soc,
            usable_capacity_wh=usable_capacity_wh,
            measured_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
            confidence=1.0,
            evidence_ids=("measurement:invalid",),
        )
