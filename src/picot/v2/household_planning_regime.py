"""Deterministic household objective profile and adaptive planning regime."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite

METHOD_VERSION = "adaptive-household-planning-regime:v1"

_COST_FIRST = (
    "cost_optimization",
    "self_consumption",
    "reserve_availability",
)
_SELF_CONSUMPTION_FIRST = (
    "self_consumption",
    "cost_optimization",
    "reserve_availability",
)


@dataclass(frozen=True, slots=True)
class UserObjectiveProfile:
    """Explicit user-owned objectives; never changed autonomously by PicoT."""

    profile_id: str
    version: int
    cost_optimization_weight: int
    self_consumption_weight: int
    reserve_availability_weight: int
    trading_enabled: bool
    adaptive_priority_enabled: bool

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id must be explicit")
        if self.version < 1:
            raise ValueError("profile version must be positive")
        for weight in (
            self.cost_optimization_weight,
            self.self_consumption_weight,
            self.reserve_availability_weight,
        ):
            if not 0 <= weight <= 100:
                raise ValueError("objective weight must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class AdaptiveHouseholdObjectivePolicy:
    """User-configurable evidence thresholds for the adaptive profile."""

    low_pv_confidence_threshold: float = 0.50
    minimum_underperformance_percent: float = 20.0
    minimum_underperformance_wh: float = 500.0
    minimum_underperformance_duration_seconds: int = 1800

    def __post_init__(self) -> None:
        if not 0.0 <= self.low_pv_confidence_threshold <= 1.0:
            raise ValueError("PV confidence threshold must be between 0 and 1")
        for value in (
            self.minimum_underperformance_percent,
            self.minimum_underperformance_wh,
        ):
            if value < 0.0 or not isfinite(value):
                raise ValueError("underperformance threshold must be finite and non-negative")
        if self.minimum_underperformance_duration_seconds < 0:
            raise ValueError("underperformance duration must be non-negative")


@dataclass(frozen=True, slots=True)
class HouseholdPlanningRegime:
    """One immutable, evidence-backed objective order for a Planner Run."""

    regime_id: str
    profile_id: str
    profile_version: int
    regime: str
    objective_order: tuple[str, ...]
    reason: str
    forecast_confidence: float
    cumulative_forecast_energy_wh: float
    cumulative_actual_energy_wh: float
    deviation_energy_wh: float
    deviation_percent: float | None
    underperformance_duration_seconds: int
    evidence_ids: tuple[str, ...]
    method_version: str = METHOD_VERSION

    def __post_init__(self) -> None:
        if self.regime not in {
            "cost_optimization_first",
            "self_consumption_first",
        }:
            raise ValueError("household planning regime is unsupported")
        if not 0.0 <= self.forecast_confidence <= 1.0:
            raise ValueError("forecast confidence must be between 0 and 1")
        for value in (
            self.cumulative_forecast_energy_wh,
            self.cumulative_actual_energy_wh,
        ):
            if value < 0.0 or not isfinite(value):
                raise ValueError("PV energy must be finite and non-negative")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("evidence IDs must be explicit")


def derive_household_planning_regime(
    *,
    profile: UserObjectiveProfile,
    policy: AdaptiveHouseholdObjectivePolicy,
    forecast_confidence: float,
    cumulative_forecast_energy_wh: float,
    cumulative_actual_energy_wh: float,
    underperformance_duration_seconds: int,
    evidence_ids: tuple[str, ...],
) -> HouseholdPlanningRegime:
    """Apply the user's adaptive preference to canonical PV evidence."""

    if not 0.0 <= forecast_confidence <= 1.0:
        raise ValueError("forecast confidence must be between 0 and 1")
    if cumulative_forecast_energy_wh < 0.0 or cumulative_actual_energy_wh < 0.0:
        raise ValueError("PV energy must be non-negative")
    if underperformance_duration_seconds < 0:
        raise ValueError("underperformance duration must be non-negative")

    deviation_wh = cumulative_actual_energy_wh - cumulative_forecast_energy_wh
    deviation_percent = (
        deviation_wh / cumulative_forecast_energy_wh * 100.0
        if cumulative_forecast_energy_wh > 0.0
        else None
    )
    low_confidence = forecast_confidence <= policy.low_pv_confidence_threshold
    material_wh = -deviation_wh >= policy.minimum_underperformance_wh
    material_percent = (
        deviation_percent is not None
        and -deviation_percent >= policy.minimum_underperformance_percent
    )
    sustained = (
        underperformance_duration_seconds
        >= policy.minimum_underperformance_duration_seconds
    )
    prioritize_self_consumption = (
        profile.adaptive_priority_enabled
        and low_confidence
        and material_wh
        and material_percent
        and sustained
    )

    if not profile.adaptive_priority_enabled:
        regime = "cost_optimization_first"
        objective_order = _COST_FIRST
        reason = "adaptive_priority_disabled"
    elif prioritize_self_consumption:
        regime = "self_consumption_first"
        objective_order = _SELF_CONSUMPTION_FIRST
        reason = "low_confidence_and_material_pv_underperformance"
    else:
        regime = "cost_optimization_first"
        objective_order = _COST_FIRST
        reason = "adaptive_switch_conditions_not_met"

    unique_evidence_ids = tuple(dict.fromkeys(evidence_ids))
    seed = "|".join(
        (
            profile.profile_id,
            str(profile.version),
            regime,
            reason,
            str(forecast_confidence),
            str(cumulative_forecast_energy_wh),
            str(cumulative_actual_energy_wh),
            str(underperformance_duration_seconds),
            *unique_evidence_ids,
            METHOD_VERSION,
        )
    )
    return HouseholdPlanningRegime(
        regime_id=f"household-regime-{sha256(seed.encode('utf-8')).hexdigest()[:16]}",
        profile_id=profile.profile_id,
        profile_version=profile.version,
        regime=regime,
        objective_order=objective_order,
        reason=reason,
        forecast_confidence=forecast_confidence,
        cumulative_forecast_energy_wh=cumulative_forecast_energy_wh,
        cumulative_actual_energy_wh=cumulative_actual_energy_wh,
        deviation_energy_wh=deviation_wh,
        deviation_percent=deviation_percent,
        underperformance_duration_seconds=underperformance_duration_seconds,
        evidence_ids=unique_evidence_ids,
    )
