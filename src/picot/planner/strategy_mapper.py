"""Translate user-visible preferences into internal Planner weights.

The mapping is explicit, deterministic and versioned. It is based on the
non-linear example accepted in ADR-018 and can later be replaced only through a
new mapping version.
"""

from __future__ import annotations

from dataclasses import dataclass

from picot.domain.objectives import (
    ObjectivePreference,
    ObjectiveWeight,
    PlannerStrategy,
    UserObjectivePreferences,
    WeightedObjective,
)


@dataclass(frozen=True, slots=True)
class ObjectiveMappingPolicy:
    """Versioned piecewise-linear mapping from UI values to Planner weights."""

    version: str
    points: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("Mapping policy version must not be empty.")
        if len(self.points) < 2:
            raise ValueError("Mapping policy requires at least two points.")
        visible_values = [visible for visible, _ in self.points]
        internal_values = [internal for _, internal in self.points]
        if visible_values != sorted(set(visible_values)):
            raise ValueError("Visible mapping points must be unique and increasing.")
        if internal_values != sorted(internal_values):
            raise ValueError("Internal mapping values must be non-decreasing.")
        if self.points[0] != (0, 0) or self.points[-1] != (100, 1000):
            raise ValueError("Mapping policy must span (0, 0) through (100, 1000).")

    def map_value(self, visible_value: int) -> ObjectiveWeight:
        """Map a validated 0..100 UI value through linear interpolation."""

        if not 0 <= visible_value <= 100:
            raise ValueError("Visible value must be between 0 and 100.")

        for left, right in zip(self.points, self.points[1:]):
            left_visible, left_internal = left
            right_visible, right_internal = right
            if left_visible <= visible_value <= right_visible:
                if visible_value == left_visible:
                    return ObjectiveWeight(left_internal)
                width = right_visible - left_visible
                position = visible_value - left_visible
                mapped = left_internal + (right_internal - left_internal) * position / width
                return ObjectiveWeight(round(mapped))

        raise RuntimeError("Mapping policy did not cover the validated visible value.")


DEFAULT_OBJECTIVE_MAPPING = ObjectiveMappingPolicy(
    version="objective-map-v1",
    points=(
        (0, 0),
        (10, 100),
        (20, 200),
        (30, 300),
        (40, 450),
        (50, 600),
        (60, 720),
        (70, 830),
        (80, 910),
        (90, 970),
        (100, 1000),
    ),
)


@dataclass(frozen=True, slots=True)
class PlannerStrategyMapper:
    """Create an immutable Planner Strategy from user-facing preferences."""

    policy: ObjectiveMappingPolicy = DEFAULT_OBJECTIVE_MAPPING

    def map(
        self,
        preferences: UserObjectivePreferences,
        *,
        strategy_version: int,
    ) -> PlannerStrategy:
        """Map all explicit preferences without adding hidden objectives."""

        weighted = tuple(self._map_preference(item) for item in preferences.objectives)
        return PlannerStrategy(
            strategy_version=strategy_version,
            source_profile_version=preferences.profile_version,
            mapping_version=self.policy.version,
            optimisation_profile=preferences.optimisation_profile,
            objectives=weighted,
        )

    def _map_preference(self, preference: ObjectivePreference) -> WeightedObjective:
        return WeightedObjective(
            objective=preference.objective,
            weight=self.policy.map_value(preference.setting.value),
        )
