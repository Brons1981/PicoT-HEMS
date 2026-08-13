from __future__ import annotations

import pytest

from picot.addon.live_objective_strategy import (
    live_planner_strategy_from_options,
    strategy_observer_fields,
)
from picot.domain.objectives import ObjectiveKind, OptimisationProfile


def test_missing_objective_settings_remain_zero_without_hidden_defaults() -> None:
    strategy = live_planner_strategy_from_options({})

    assert strategy.optimisation_profile is OptimisationProfile.BALANCED
    assert all(item.weight.value == 0 for item in strategy.objectives)
    assert strategy.weight_for(ObjectiveKind.FINANCIAL_RESULT).value == 0
    assert strategy.weight_for(ObjectiveKind.SELF_CONSUMPTION).value == 0


def test_explicit_user_settings_are_mapped_through_adr018_mapper() -> None:
    strategy = live_planner_strategy_from_options(
        {
            "optimisation_profile": "active",
            "objective_financial_result": 80,
            "objective_self_consumption": 40,
            "objective_net_balance": 20,
        }
    )

    assert strategy.optimisation_profile is OptimisationProfile.ACTIVE
    assert strategy.mapping_version == "objective-map-v1"
    assert strategy.weight_for(ObjectiveKind.FINANCIAL_RESULT).value == 910
    assert strategy.weight_for(ObjectiveKind.SELF_CONSUMPTION).value == 450
    assert strategy.weight_for(ObjectiveKind.NET_BALANCE).value == 200
    assert strategy.weight_for(ObjectiveKind.BATTERY_LONGEVITY).value == 0


def test_observer_fields_expose_exact_vector_consumed_by_evaluation() -> None:
    strategy = live_planner_strategy_from_options(
        {"objective_self_consumption": 50}
    )

    fields = strategy_observer_fields(strategy)

    assert fields["planner_strategy_mapping_version"] == "objective-map-v1"
    assert fields["planner_optimisation_profile"] == "balanced"
    assert fields["planner_objective_count"] == 7
    assert fields["planner_objectives"]["self_consumption"] == 600
    assert fields["planner_objectives"]["financial_result"] == 0


def test_invalid_objective_setting_fails_closed() -> None:
    with pytest.raises(ValueError, match="objective_financial_result"):
        live_planner_strategy_from_options({"objective_financial_result": 101})
