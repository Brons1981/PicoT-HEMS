"""Build the live PlannerStrategy only from explicit user objective settings.

ADR-018/025 require user objectives to remain explicit, versioned and mapped
through the Objective Mapping Layer. This module owns only that translation.
It does not choose objectives, rank candidates or invent preset weights.
"""

from __future__ import annotations

from collections.abc import Mapping

from picot.domain.objectives import (
    ObjectiveKind,
    ObjectivePreference,
    OptimisationProfile,
    PlannerStrategy,
    UserObjectivePreferences,
    VisibleObjectiveSetting,
)
from picot.planner.strategy_mapper import PlannerStrategyMapper

_OBJECTIVE_OPTION_KEYS: tuple[tuple[str, ObjectiveKind], ...] = (
    ("objective_financial_result", ObjectiveKind.FINANCIAL_RESULT),
    ("objective_self_consumption", ObjectiveKind.SELF_CONSUMPTION),
    ("objective_battery_longevity", ObjectiveKind.BATTERY_LONGEVITY),
    ("objective_dynamic_trading", ObjectiveKind.DYNAMIC_TRADING),
    ("objective_reserve_availability", ObjectiveKind.RESERVE_AVAILABILITY),
    ("objective_sustainability", ObjectiveKind.SUSTAINABILITY),
    ("objective_net_balance", ObjectiveKind.NET_BALANCE),
)


def live_planner_strategy_from_options(
    options: Mapping[str, object],
) -> PlannerStrategy:
    """Map explicit add-on settings to the immutable live PlannerStrategy.

    Missing objective settings are treated as zero rather than receiving a
    hidden default. The optimisation profile is separately explicit because
    ADR-025 does not permit it to imply objective weights.
    """

    profile_raw = str(options.get("optimisation_profile", OptimisationProfile.BALANCED.value))
    profile = OptimisationProfile(profile_raw)
    profile_version = _integer_option(options, "objective_profile_version", default=1, minimum=1)
    strategy_version = _integer_option(options, "strategy_version", default=1, minimum=1)

    preferences = UserObjectivePreferences(
        profile_version=profile_version,
        optimisation_profile=profile,
        objectives=tuple(
            ObjectivePreference(
                objective=objective,
                setting=VisibleObjectiveSetting(
                    _integer_option(options, option_key, default=0, minimum=0, maximum=100)
                ),
            )
            for option_key, objective in _OBJECTIVE_OPTION_KEYS
        ),
    )
    return PlannerStrategyMapper().map(
        preferences,
        strategy_version=strategy_version,
    )


def strategy_observer_fields(strategy: PlannerStrategy) -> dict[str, object]:
    """Expose the exact immutable objective vector consumed by Evaluation."""

    return {
        "planner_strategy_version": strategy.strategy_version,
        "planner_strategy_source_profile_version": strategy.source_profile_version,
        "planner_strategy_mapping_version": strategy.mapping_version,
        "planner_optimisation_profile": strategy.optimisation_profile.value,
        "planner_objective_count": len(strategy.objectives),
        "planner_objectives": {
            item.objective.value: item.weight.value for item in strategy.objectives
        },
    }


def _integer_option(
    options: Mapping[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    raw = options.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be numeric.")
    value = int(raw)
    if float(raw) != float(value):
        raise ValueError(f"{key} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and {maximum}" if maximum is not None else ""
        raise ValueError(f"{key} must be between {minimum}{upper}.")
    return value
