"""Attach explicit household objectives to one immutable Planning Input."""

from __future__ import annotations

from dataclasses import replace

from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    UserObjectiveProfile,
    derive_household_planning_regime,
)


def attach_household_objectives(
    snapshot: PlanningInputSnapshot,
    *,
    profile: UserObjectiveProfile,
    policy: AdaptiveHouseholdObjectivePolicy,
    forecast_confidence: float,
    cumulative_forecast_energy_wh: float,
    cumulative_actual_energy_wh: float,
    underperformance_duration_seconds: int,
    evidence_ids: tuple[str, ...],
) -> PlanningInputSnapshot:
    """Return a new snapshot with one evidence-backed strategy regime."""

    regime = derive_household_planning_regime(
        profile=profile,
        policy=policy,
        forecast_confidence=forecast_confidence,
        cumulative_forecast_energy_wh=cumulative_forecast_energy_wh,
        cumulative_actual_energy_wh=cumulative_actual_energy_wh,
        underperformance_duration_seconds=underperformance_duration_seconds,
        evidence_ids=evidence_ids,
    )
    return replace(
        snapshot,
        strategy_id=f"{profile.profile_id}:{profile.version}",
        user_objective_profile=profile,
        household_planning_regime=regime,
    )
