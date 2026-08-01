"""Domain models for user preferences and internal planner objectives.

The user-facing values are deliberately separated from the internal objective
weights used by the Planner. See ADR-018 and ADR-025.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ObjectiveKind(StrEnum):
    """Objectives currently understood by the Planner Strategy Model."""

    FINANCIAL_RESULT = "financial_result"
    SELF_CONSUMPTION = "self_consumption"
    BATTERY_LONGEVITY = "battery_longevity"
    DYNAMIC_TRADING = "dynamic_trading"
    RESERVE_AVAILABILITY = "reserve_availability"
    SUSTAINABILITY = "sustainability"
    NET_BALANCE = "net_balance"


class OptimisationProfile(StrEnum):
    """User-selected optimisation intensity."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    ACTIVE = "active"
    MAXIMUM = "maximum"


@dataclass(frozen=True, slots=True)
class VisibleObjectiveSetting:
    """User-facing objective setting on a 0..100 scale."""

    value: int

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 100:
            raise ValueError("Visible objective setting must be between 0 and 100.")


@dataclass(frozen=True, slots=True)
class ObjectiveWeight:
    """Internal Planner weight on a 0..1000 scale."""

    value: int

    def __post_init__(self) -> None:
        if not 0 <= self.value <= 1000:
            raise ValueError("Objective weight must be between 0 and 1000.")


@dataclass(frozen=True, slots=True)
class ObjectivePreference:
    """One user-visible objective preference."""

    objective: ObjectiveKind
    setting: VisibleObjectiveSetting


@dataclass(frozen=True, slots=True)
class WeightedObjective:
    """One internal objective and its mapped Planner weight."""

    objective: ObjectiveKind
    weight: ObjectiveWeight


@dataclass(frozen=True, slots=True)
class UserObjectivePreferences:
    """Immutable, versioned user-facing objective configuration."""

    profile_version: int
    optimisation_profile: OptimisationProfile
    objectives: tuple[ObjectivePreference, ...]

    def __post_init__(self) -> None:
        if self.profile_version < 1:
            raise ValueError("Profile version must be at least 1.")
        objective_ids = [item.objective for item in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("Each objective may appear only once in user preferences.")


@dataclass(frozen=True, slots=True)
class PlannerStrategy:
    """Immutable internal strategy consumed by the Planning Pipeline."""

    strategy_version: int
    source_profile_version: int
    mapping_version: str
    optimisation_profile: OptimisationProfile
    objectives: tuple[WeightedObjective, ...]

    def __post_init__(self) -> None:
        if self.strategy_version < 1:
            raise ValueError("Strategy version must be at least 1.")
        if self.source_profile_version < 1:
            raise ValueError("Source profile version must be at least 1.")
        if not self.mapping_version.strip():
            raise ValueError("Mapping version must not be empty.")
        objective_ids = [item.objective for item in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("Each objective may appear only once in a Planner strategy.")

    def weight_for(self, objective: ObjectiveKind) -> ObjectiveWeight:
        """Return the mapped weight for an objective.

        Missing objectives are deliberately treated as zero. This prevents hidden
        weights from entering evaluation while allowing future objectives to be
        introduced without changing every stored profile.
        """

        for item in self.objectives:
            if item.objective is objective:
                return item.weight
        return ObjectiveWeight(0)
