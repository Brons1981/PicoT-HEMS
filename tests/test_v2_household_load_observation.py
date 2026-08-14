import math

import pytest

from picot.v2.household_load_forecast import (
    derive_household_load_power_w,
)
from picot.v2.planning_input import (
    derive_validated_storage_power_w,
)


@pytest.mark.parametrize(
    (
        "grid_power_w",
        "pv_power_w",
        "battery_power_w",
        "expected_load_w",
    ),
    (
        (200.0, 1000.0, 300.0, 900.0),
        (0.0, 200.0, -500.0, 700.0),
        (-400.0, 1200.0, 300.0, 500.0),
    ),
)
def test_household_load_observation_uses_complete_power_balance(
    grid_power_w: float,
    pv_power_w: float,
    battery_power_w: float,
    expected_load_w: float,
) -> None:
    assert derive_household_load_power_w(
        grid_power_w=grid_power_w,
        pv_power_w=pv_power_w,
        battery_power_w=battery_power_w,
    ) == pytest.approx(expected_load_w)


@pytest.mark.parametrize(
    ("grid_power_w", "pv_power_w", "battery_power_w"),
    (
        (None, 1000.0, 300.0),
        (200.0, None, 300.0),
        (200.0, 1000.0, None),
        (math.nan, 1000.0, 300.0),
        (200.0, math.inf, 300.0),
        (-1000.0, 0.0, 0.0),
    ),
)
def test_household_load_observation_rejects_incomplete_or_invalid_balance(
    grid_power_w: float | None,
    pv_power_w: float | None,
    battery_power_w: float | None,
) -> None:
    assert derive_household_load_power_w(
        grid_power_w=grid_power_w,
        pv_power_w=pv_power_w,
        battery_power_w=battery_power_w,
    ) is None


@pytest.mark.parametrize(
    (
        "signed_power_w",
        "power_to_house_w",
        "power_from_house_w",
        "expected_power_w",
    ),
    (
        (-86.0, 86.0, 0.0, -86.0),
        (1200.0, 0.0, 1190.0, 1200.0),
        (0.0, 0.0, 0.0, 0.0),
    ),
)
def test_storage_power_requires_consistent_directional_evidence(
    signed_power_w: float,
    power_to_house_w: float,
    power_from_house_w: float,
    expected_power_w: float,
) -> None:
    assert derive_validated_storage_power_w(
        signed_power_w=signed_power_w,
        power_to_house_w=power_to_house_w,
        power_from_house_w=power_from_house_w,
    ) == pytest.approx(expected_power_w)


@pytest.mark.parametrize(
    (
        "signed_power_w",
        "power_to_house_w",
        "power_from_house_w",
    ),
    (
        (-86.0, 400.0, 0.0),
        (1200.0, 0.0, 900.0),
        (None, 0.0, 0.0),
        (math.nan, 0.0, 0.0),
        (0.0, math.inf, 0.0),
    ),
)
def test_storage_power_rejects_missing_invalid_or_inconsistent_evidence(
    signed_power_w: float | None,
    power_to_house_w: float,
    power_from_house_w: float,
) -> None:
    assert derive_validated_storage_power_w(
        signed_power_w=signed_power_w,
        power_to_house_w=power_to_house_w,
        power_from_house_w=power_from_house_w,
    ) is None
