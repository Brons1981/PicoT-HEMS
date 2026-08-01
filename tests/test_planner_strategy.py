from __future__ import annotations

import pytest

from picot.domain.objectives import (
    ObjectiveKind,
    ObjectivePreference,
    ObjectiveWeight,
    OptimisationProfile,
    UserObjectivePreferences,
    VisibleObjectiveSetting,
)
from picot.planner.strategy_mapper import DEFAULT_OBJECTIVE_MAPPING, PlannerStrategyMapper


def test_visible_setting_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        VisibleObjectiveSetting(-1)
    with pytest.raises(ValueError):
        VisibleObjectiveSetting(101)


def test_internal_weight_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        ObjectiveWeight(-1)
    with pytest.raises(ValueError):
        ObjectiveWeight(1001)


def test_default_mapping_is_deterministic_and_non_linear() -> None:
    assert DEFAULT_OBJECTIVE_MAPPING.map_value(0) == ObjectiveWeight(0)
    assert DEFAULT_OBJECTIVE_MAPPING.map_value(50) == ObjectiveWeight(600)
    assert DEFAULT_OBJECTIVE_MAPPING.map_value(100) == ObjectiveWeight(1000)
    assert DEFAULT_OBJECTIVE_MAPPING.map_value(55) == ObjectiveWeight(660)


def test_mapper_preserves_only_explicit_user_objectives() -> None:
    preferences = UserObjectivePreferences(
        profile_version=3,
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(
            ObjectivePreference(
                objective=ObjectiveKind.FINANCIAL_RESULT,
                setting=VisibleObjectiveSetting(50),
            ),
            ObjectivePreference(
                objective=ObjectiveKind.NET_BALANCE,
                setting=VisibleObjectiveSetting(20),
            ),
        ),
    )

    strategy = PlannerStrategyMapper().map(preferences, strategy_version=7)

    assert strategy.strategy_version == 7
    assert strategy.source_profile_version == 3
    assert strategy.mapping_version == "objective-map-v1"
    assert strategy.weight_for(ObjectiveKind.FINANCIAL_RESULT) == ObjectiveWeight(600)
    assert strategy.weight_for(ObjectiveKind.NET_BALANCE) == ObjectiveWeight(200)
    assert strategy.weight_for(ObjectiveKind.BATTERY_LONGEVITY) == ObjectiveWeight(0)


def test_duplicate_objectives_are_rejected() -> None:
    duplicate = ObjectivePreference(
        objective=ObjectiveKind.SELF_CONSUMPTION,
        setting=VisibleObjectiveSetting(50),
    )
    with pytest.raises(ValueError):
        UserObjectivePreferences(
            profile_version=1,
            optimisation_profile=OptimisationProfile.ACTIVE,
            objectives=(duplicate, duplicate),
        )
