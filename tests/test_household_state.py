from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from picot.domain.household_state import HouseholdState, Phase, PhaseState


def test_phase_state_applies_operational_margin() -> None:
    phase = PhaseState(
        phase=Phase.L1,
        current_a=20.0,
        voltage_v=236.0,
        active_power_w=4720.0,
        main_fuse_limit_a=25.0,
        operational_margin_a=2.0,
    )

    assert phase.operational_limit_a == 23.0
    assert phase.available_current_a == 3.0


def test_phase_state_allows_unavailable_measurements() -> None:
    phase = PhaseState(
        phase=Phase.L2,
        current_a=None,
        voltage_v=None,
        active_power_w=None,
        main_fuse_limit_a=25.0,
    )

    assert phase.available_current_a is None


def test_phase_state_rejects_invalid_limits_and_measurements() -> None:
    with pytest.raises(ValueError, match="current must not be negative"):
        PhaseState(Phase.L1, -0.1, 230.0, None, 25.0)
    with pytest.raises(ValueError, match="voltage must be greater than zero"):
        PhaseState(Phase.L1, 1.0, 0.0, None, 25.0)
    with pytest.raises(ValueError, match="below the fuse limit"):
        PhaseState(Phase.L1, 1.0, 230.0, None, 25.0, 25.0)


def test_household_state_rejects_duplicate_phases() -> None:
    phase = PhaseState(Phase.L3, 2.0, 253.0, 506.0, 25.0)

    with pytest.raises(ValueError, match="may appear only once"):
        HouseholdState(
            measured_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            phases=(phase, phase),
        )


def test_household_state_requires_timezone_aware_time() -> None:
    with pytest.raises(ValueError, match="must be timezone-aware"):
        HouseholdState(measured_at=datetime(2026, 8, 1, 12, 0), phases=())


def test_household_state_is_immutable() -> None:
    state = HouseholdState(
        measured_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        phases=(),
    )

    with pytest.raises(FrozenInstanceError):
        state.grid_power_w = 100.0  # type: ignore[misc]
