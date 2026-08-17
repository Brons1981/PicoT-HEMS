"""Attach explicit household objectives to one immutable Planning Input."""

from __future__ import annotations

from dataclasses import replace

from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    HouseholdPlanningRegime,
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
    previous_regime: HouseholdPlanningRegime | None = None,
    previous_regime_duration_seconds: int = 0,
    recovery_duration_seconds: int = 0,
    overperformance_duration_seconds: int = 0,
    remaining_storage_need_wh: float | None = None,
    conservative_remaining_pv_surplus_wh: float | None = None,
    remaining_pv_storage_margin_wh: float | None = None,
    storage_target_required_by: str | None = None,
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
        previous_regime=(
            previous_regime.regime if previous_regime is not None else None
        ),
        previous_regime_duration_seconds=previous_regime_duration_seconds,
        recovery_duration_seconds=recovery_duration_seconds,
        overperformance_duration_seconds=overperformance_duration_seconds,
        remaining_storage_need_wh=remaining_storage_need_wh,
        conservative_remaining_pv_surplus_wh=(
            conservative_remaining_pv_surplus_wh
        ),
        remaining_pv_storage_margin_wh=remaining_pv_storage_margin_wh,
        storage_target_required_by=storage_target_required_by,
    )
    return replace(
        snapshot,
        strategy_id=f"{profile.profile_id}:{profile.version}",
        user_objective_profile=profile,
        household_planning_regime=regime,
    )
