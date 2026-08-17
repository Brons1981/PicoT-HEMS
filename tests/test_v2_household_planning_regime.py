import pytest

from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    UserObjectiveProfile,
    derive_household_planning_regime,
)


def _profile(*, adaptive: bool = True) -> UserObjectiveProfile:
    return UserObjectiveProfile(
        profile_id="profile:alex:v1",
        version=1,
        cost_optimization_weight=80,
        self_consumption_weight=70,
        reserve_availability_weight=60,
        trading_enabled=False,
        adaptive_priority_enabled=adaptive,
    )


def test_low_confidence_and_material_pv_underperformance_prioritizes_self_consumption() -> None:
    regime = derive_household_planning_regime(
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(
            low_pv_confidence_threshold=0.50,
            minimum_underperformance_percent=20.0,
            minimum_underperformance_wh=500.0,
            minimum_underperformance_duration_seconds=1800,
        ),
        forecast_confidence=0.35,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=2500.0,
        underperformance_duration_seconds=3600,
        evidence_ids=("solcast-forecast-1", "goodwe-actual-1"),
    )

    assert regime.regime == "self_consumption_first"
    assert regime.objective_order == (
        "self_consumption",
        "cost_optimization",
        "reserve_availability",
    )
    assert regime.deviation_energy_wh == -1500.0
    assert regime.deviation_percent == pytest.approx(-37.5)
    assert regime.reason == "low_confidence_and_material_pv_underperformance"
    assert regime.evidence_ids == (
        "solcast-forecast-1",
        "goodwe-actual-1",
    )


@pytest.mark.parametrize(
    ("forecast_confidence", "actual_wh", "duration_seconds"),
    (
        (0.75, 2500.0, 3600),
        (0.35, 3700.0, 3600),
        (0.35, 2500.0, 900),
    ),
)
def test_one_signal_alone_does_not_change_the_user_strategy(
    forecast_confidence: float,
    actual_wh: float,
    duration_seconds: int,
) -> None:
    regime = derive_household_planning_regime(
        profile=_profile(),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=forecast_confidence,
        cumulative_forecast_energy_wh=4000.0,
        cumulative_actual_energy_wh=actual_wh,
        underperformance_duration_seconds=duration_seconds,
        evidence_ids=("solcast-forecast-1", "goodwe-actual-1"),
    )

    assert regime.regime == "cost_optimization_first"
    assert regime.objective_order[0] == "cost_optimization"


def test_disabled_adaptive_policy_never_reorders_objectives() -> None:
    regime = derive_household_planning_regime(
        profile=_profile(adaptive=False),
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=0.10,
        cumulative_forecast_energy_wh=5000.0,
        cumulative_actual_energy_wh=1000.0,
        underperformance_duration_seconds=7200,
        evidence_ids=("solcast-forecast-1", "goodwe-actual-1"),
    )

    assert regime.regime == "cost_optimization_first"
    assert regime.reason == "adaptive_priority_disabled"


def test_trading_is_a_user_choice_and_not_part_of_regime_derivation() -> None:
    profile = _profile()
    regime = derive_household_planning_regime(
        profile=profile,
        policy=AdaptiveHouseholdObjectivePolicy(),
        forecast_confidence=1.0,
        cumulative_forecast_energy_wh=1000.0,
        cumulative_actual_energy_wh=1000.0,
        underperformance_duration_seconds=0,
        evidence_ids=("solcast-forecast-1", "goodwe-actual-1"),
    )

    assert profile.trading_enabled is False
    assert "trading" not in regime.objective_order


def test_profile_rejects_hidden_or_invalid_weights() -> None:
    with pytest.raises(ValueError, match="objective weight"):
        UserObjectiveProfile(
            profile_id="profile:invalid",
            version=1,
            cost_optimization_weight=101,
            self_consumption_weight=50,
            reserve_availability_weight=50,
            trading_enabled=False,
            adaptive_priority_enabled=True,
        )
