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
    minimum_self_consumption_hold_seconds: int = 7200
    recovery_confidence_threshold: float = 0.60
    maximum_recovery_deficit_percent: float = 10.0
    maximum_recovery_deficit_wh: float = 250.0
    minimum_recovery_duration_seconds: int = 3600
    minimum_overperformance_percent: float = 20.0
    minimum_overperformance_wh: float = 500.0
    minimum_overperformance_duration_seconds: int = 3600
    minimum_conservative_pv_storage_margin_wh: float = 500.0

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
        if not 0.0 <= self.recovery_confidence_threshold <= 1.0:
            raise ValueError("recovery confidence threshold must be between 0 and 1")
        for value in (
            self.maximum_recovery_deficit_percent,
            self.maximum_recovery_deficit_wh,
            self.minimum_overperformance_percent,
            self.minimum_overperformance_wh,
            self.minimum_conservative_pv_storage_margin_wh,
        ):
            if value < 0.0 or not isfinite(value):
                raise ValueError("hysteresis threshold must be finite and non-negative")
        for value in (
            self.minimum_self_consumption_hold_seconds,
            self.minimum_recovery_duration_seconds,
            self.minimum_overperformance_duration_seconds,
        ):
            if value < 0:
                raise ValueError("hysteresis duration must be non-negative")


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
    remaining_storage_need_wh: float | None = None
    conservative_remaining_pv_surplus_wh: float | None = None
    remaining_pv_storage_margin_wh: float | None = None
    storage_target_at_risk: bool = False
    storage_target_required_by: str | None = None
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
    previous_regime: str | None = None,
    previous_regime_duration_seconds: int = 0,
    recovery_duration_seconds: int = 0,
    overperformance_duration_seconds: int = 0,
    remaining_storage_need_wh: float | None = None,
    conservative_remaining_pv_surplus_wh: float | None = None,
    remaining_pv_storage_margin_wh: float | None = None,
    storage_target_required_by: str | None = None,
) -> HouseholdPlanningRegime:
    """Apply the user's adaptive preference to canonical PV evidence."""

    if not 0.0 <= forecast_confidence <= 1.0:
        raise ValueError("forecast confidence must be between 0 and 1")
    if cumulative_forecast_energy_wh < 0.0 or cumulative_actual_energy_wh < 0.0:
        raise ValueError("PV energy must be non-negative")
    for duration in (
        underperformance_duration_seconds,
        previous_regime_duration_seconds,
        recovery_duration_seconds,
        overperformance_duration_seconds,
    ):
        if duration < 0:
            raise ValueError("regime duration must be non-negative")
    if previous_regime not in {
        None,
        "cost_optimization_first",
        "self_consumption_first",
    }:
        raise ValueError("previous household planning regime is unsupported")

    feasibility_values = (
        remaining_storage_need_wh,
        conservative_remaining_pv_surplus_wh,
        remaining_pv_storage_margin_wh,
    )
    if any(value is not None and not isfinite(value) for value in feasibility_values):
        raise ValueError("storage feasibility values must be finite")
    if remaining_storage_need_wh is not None and remaining_storage_need_wh < 0.0:
        raise ValueError("remaining storage need must be non-negative")
    if (
        conservative_remaining_pv_surplus_wh is not None
        and conservative_remaining_pv_surplus_wh < 0.0
    ):
        raise ValueError("conservative remaining PV surplus must be non-negative")

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
    recovered = (
        forecast_confidence >= policy.recovery_confidence_threshold
        and deviation_wh >= -policy.maximum_recovery_deficit_wh
        and (
            deviation_percent is not None
            and deviation_percent >= -policy.maximum_recovery_deficit_percent
        )
        and recovery_duration_seconds >= policy.minimum_recovery_duration_seconds
    )
    structurally_above_forecast = (
        deviation_wh >= policy.minimum_overperformance_wh
        and (
            deviation_percent is not None
            and deviation_percent >= policy.minimum_overperformance_percent
        )
        and overperformance_duration_seconds
        >= policy.minimum_overperformance_duration_seconds
    )
    hold_complete = (
        previous_regime_duration_seconds
        >= policy.minimum_self_consumption_hold_seconds
    )
    storage_target_at_risk = (
        remaining_storage_need_wh is not None
        and remaining_storage_need_wh > 0.0
        and remaining_pv_storage_margin_wh is not None
        and remaining_pv_storage_margin_wh
        <= policy.minimum_conservative_pv_storage_margin_wh
    )

    if not profile.adaptive_priority_enabled:
        regime = "cost_optimization_first"
        objective_order = _COST_FIRST
        reason = "adaptive_priority_disabled"
    elif storage_target_at_risk:
        regime = "self_consumption_first"
        objective_order = _SELF_CONSUMPTION_FIRST
        reason = "conservative_pv_storage_margin_at_risk"
    elif previous_regime == "self_consumption_first" and not hold_complete:
        regime = "self_consumption_first"
        objective_order = _SELF_CONSUMPTION_FIRST
        reason = "minimum_self_consumption_hold_active"
    elif previous_regime == "self_consumption_first" and recovered:
        regime = "cost_optimization_first"
        objective_order = _COST_FIRST
        reason = "sustained_pv_recovery"
    elif (
        previous_regime == "self_consumption_first"
        and structurally_above_forecast
    ):
        regime = "cost_optimization_first"
        objective_order = _COST_FIRST
        reason = "actual_pv_structurally_above_forecast"
    elif previous_regime == "self_consumption_first":
        regime = "self_consumption_first"
        objective_order = _SELF_CONSUMPTION_FIRST
        reason = "self_consumption_hysteresis_active"
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
            str(previous_regime),
            str(previous_regime_duration_seconds),
            str(recovery_duration_seconds),
            str(overperformance_duration_seconds),
            str(remaining_storage_need_wh),
            str(conservative_remaining_pv_surplus_wh),
            str(remaining_pv_storage_margin_wh),
            str(storage_target_required_by),
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
        remaining_storage_need_wh=remaining_storage_need_wh,
        conservative_remaining_pv_surplus_wh=(
            conservative_remaining_pv_surplus_wh
        ),
        remaining_pv_storage_margin_wh=remaining_pv_storage_margin_wh,
        storage_target_at_risk=storage_target_at_risk,
        storage_target_required_by=storage_target_required_by,
    )
