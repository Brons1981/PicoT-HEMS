"""Live runtime for the PicoT v2 canonical validation pipeline.

Performance diagnostics remain observational and outside planner decision logic.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from http.server import ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from threading import Thread
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from picot.v2.canonical_execution_runtime import (
    CanonicalExecutionRuntime,
    HomeAssistantCanonicalModeAdapter,
)
from picot.v2.fast_grid_power_observation import FastGridPowerObserver
from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.household_objective_input import attach_household_objectives
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    HouseholdPlanningRegime,
    UserObjectiveProfile,
)
from picot.v2.live_pv_actual import (
    LivePVActualCache,
    LivePVActualDiagnostics,
    apply_latest_closed_actual_pv,
)
from picot.v2.live_pv_canary_runtime import (
    HomeAssistantLivePVModeAdapter,
    LivePVCanaryResult,
    LivePVCanaryRuntime,
    build_live_pv_mode_input,
    live_pv_runtime_evidence,
    project_live_pv_canary_result,
)
from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
    attach_storage_mode_provenance,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline, PipelineStageTimings
from picot.v2.planning_input import (
    HomeAssistantStateReader,
    HouseholdLoadObservation,
    PlanningInputBundle,
    SourceBinding,
    assemble_planning_input,
    load_options,
)
from picot.v2.projection import Card, Projection, project
from picot.v2.pv_actual_history import HomeAssistantPVHistoryReader
from picot.v2.pv_attenuation_aggregation import (
    PVAttenuationAggregationConfig,
)
from picot.v2.pv_attenuation_eligibility import (
    PVAttenuationEligibilityConfig,
)
from picot.v2.pv_attenuation_evidence import PVAttenuationEvidenceStore
from picot.v2.pv_attenuation_learning import (
    ObserverOnlyPVAttenuationLearningRuntime,
    PVAttenuationLearningResult,
    project_pv_attenuation_learning_result,
)
from picot.v2.pv_attenuation_range import PVAttenuatedForecastRange
from picot.v2.pv_attenuation_runtime import (
    attach_pv_attenuation_runtime_diagnostics,
)
from picot.v2.pv_attenuation_runtime_derivation import (
    derive_live_pv_attenuation_ranges,
)
from picot.v2.pv_cumulative_evidence import PVCumulativeEvidence
from picot.v2.pv_deviation import PVDeviationResult
from picot.v2.pv_solar_history import HomeAssistantSolarHistoryReader
from picot.v2.pv_sunset_offsets import derive_pv_sunset_offsets
from picot.v2.pv_sunset_runtime import (
    attach_pv_sunset_runtime_diagnostics,
)
from picot.v2.pv_sunset_source import (
    HomeAssistantSunsetReader,
    SunsetReadResult,
)
from picot.v2.web_ui import (
    WebViewStore,
    build_web_view,
    create_web_server,
)

HOUSEHOLD_LOAD_HISTORY_PATH = Path(
    "/data/picot_v2_household_load_history.jsonl"
)
PV_ATTENUATION_FORECAST_BASIS_PATH = Path(
    "/data/picot_v2_pv_forecast_basis.jsonl"
)
PV_ATTENUATION_EVIDENCE_PATH = Path(
    "/data/picot_v2_pv_attenuation_evidence.jsonl"
)
STORAGE_MODE_PROVENANCE_PATH = Path(
    "/data/picot_v2_storage_mode_provenance.json"
)



def _household_objective_profile(
    options: dict[str, Any],
) -> UserObjectiveProfile:
    return UserObjectiveProfile(
        profile_id="profile:household:configured:v1",
        version=1,
        cost_optimization_weight=int(
            options.get("household_cost_optimization_weight", 80)
        ),
        self_consumption_weight=int(
            options.get("household_self_consumption_weight", 70)
        ),
        reserve_availability_weight=int(
            options.get("household_reserve_availability_weight", 60)
        ),
        trading_enabled=bool(
            options.get("household_trading_enabled", False)
        ),
        adaptive_priority_enabled=bool(
            options.get("household_adaptive_priority_enabled", True)
        ),
    )


def _adaptive_household_policy(
    options: dict[str, Any],
) -> AdaptiveHouseholdObjectivePolicy:
    return AdaptiveHouseholdObjectivePolicy(
        low_pv_confidence_threshold=float(
            options.get("household_low_pv_confidence_threshold", 0.50)
        ),
        minimum_underperformance_percent=float(
            options.get("household_minimum_pv_underperformance_percent", 20.0)
        ),
        minimum_underperformance_wh=float(
            options.get("household_minimum_pv_underperformance_wh", 500.0)
        ),
        minimum_underperformance_duration_seconds=int(
            options.get(
                "household_minimum_pv_underperformance_duration_seconds",
                1800,
            )
        ),
        minimum_self_consumption_hold_seconds=int(
            options.get("household_minimum_self_consumption_hold_seconds", 7200)
        ),
        recovery_confidence_threshold=float(
            options.get("household_recovery_confidence_threshold", 0.60)
        ),
        maximum_recovery_deficit_percent=float(
            options.get("household_maximum_recovery_deficit_percent", 10.0)
        ),
        maximum_recovery_deficit_wh=float(
            options.get("household_maximum_recovery_deficit_wh", 250.0)
        ),
        minimum_recovery_duration_seconds=int(
            options.get("household_minimum_recovery_duration_seconds", 3600)
        ),
        minimum_overperformance_percent=float(
            options.get("household_minimum_pv_overperformance_percent", 20.0)
        ),
        minimum_overperformance_wh=float(
            options.get("household_minimum_pv_overperformance_wh", 500.0)
        ),
        minimum_overperformance_duration_seconds=int(
            options.get(
                "household_minimum_pv_overperformance_duration_seconds",
                3600,
            )
        ),
    )


def _rolling_pv_direction_seconds(
    deviations: tuple[PVDeviationResult, ...],
    *,
    direction: str,
    window_seconds: int = 3600,
) -> int:
    """Count matching covered seconds in the latest evidence window."""
    if not deviations:
        return 0
    window_end = max(item.ends_at for item in deviations)
    window_start = window_end - timedelta(seconds=window_seconds)
    seconds = 0.0
    for deviation in deviations:
        if deviation.direction != direction:
            continue
        overlap_start = max(deviation.starts_at, window_start)
        overlap_end = min(deviation.ends_at, window_end)
        if overlap_end > overlap_start:
            seconds += (overlap_end - overlap_start).total_seconds()
    return int(seconds)


def _rolling_pv_recovery_seconds(
    deviations: tuple[PVDeviationResult, ...],
    *,
    window_seconds: int = 3600,
) -> int:
    """Count covered seconds that are not below the central forecast."""
    if not deviations:
        return 0
    window_end = max(item.ends_at for item in deviations)
    window_start = window_end - timedelta(seconds=window_seconds)
    seconds = 0.0
    for deviation in deviations:
        if deviation.direction == "below_forecast":
            continue
        overlap_start = max(deviation.starts_at, window_start)
        overlap_end = min(deviation.ends_at, window_end)
        if overlap_end > overlap_start:
            seconds += (overlap_end - overlap_start).total_seconds()
    return int(seconds)


def _attach_live_household_objectives(
    bundle: PlanningInputBundle,
    diagnostics: LivePVActualDiagnostics,
    *,
    profile: UserObjectiveProfile,
    policy: AdaptiveHouseholdObjectivePolicy,
    previous_regime: HouseholdPlanningRegime | None = None,
    previous_regime_duration_seconds: int = 0,
) -> PlanningInputBundle:
    cumulative = diagnostics.cumulative_evidence
    deviations = diagnostics.deviation_results
    if cumulative is None or cumulative.assessed_interval_count == 0:
        forecast_confidence = 1.0
        forecast_energy_wh = 0.0
        actual_energy_wh = 0.0
        duration_seconds = 0
        evidence_ids: tuple[str, ...] = (
            f"{profile.profile_id}:{profile.version}:pv-deviation-unavailable",
        )
    else:
        forecast_confidence = min(
            deviation.forecast_confidence for deviation in deviations
        )
        forecast_energy_wh = cumulative.forecast_central_energy_wh
        actual_energy_wh = cumulative.actual_energy_wh
        duration_seconds = _rolling_pv_direction_seconds(
            deviations,
            direction="below_forecast",
        )
        evidence_ids = (
            cumulative.evidence_id,
            *cumulative.interval_deviation_ids,
        )
    snapshot = attach_household_objectives(
        bundle.snapshot,
        profile=profile,
        policy=policy,
        forecast_confidence=forecast_confidence,
        cumulative_forecast_energy_wh=forecast_energy_wh,
        cumulative_actual_energy_wh=actual_energy_wh,
        underperformance_duration_seconds=duration_seconds,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        previous_regime=previous_regime,
        previous_regime_duration_seconds=previous_regime_duration_seconds,
        recovery_duration_seconds=_rolling_pv_recovery_seconds(deviations),
        overperformance_duration_seconds=_rolling_pv_direction_seconds(
            deviations,
            direction="above_forecast",
        ),
    )
    return replace(bundle, snapshot=snapshot)

def _planning_input_signature(bundle: PlanningInputBundle) -> str:
    """Return a stable signature for decision-relevant Planning Input content."""
    facts = [
        {
            "category": fact.category,
            "semantic_role": fact.semantic_role,
            "value": fact.value,
            "unit": fact.unit,
            "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
            "availability": fact.availability,
            "mapping_version": fact.mapping_version,
            "confidence": fact.confidence,
            "confidence_status": fact.confidence_status,
        }
        for fact in bundle.facts
    ]
    price_points = [
        {
            "starts_at": point.starts_at.isoformat(),
            "ends_at": point.ends_at.isoformat(),
            "value_eur_per_kwh": point.value_eur_per_kwh,
            "confidence": point.confidence,
        }
        for point in bundle.snapshot.price_points
    ]
    pv_timeline = bundle.snapshot.pv_energy_timeline
    pv_energy_intervals = [
        {
            "starts_at": interval.starts_at.isoformat(),
            "ends_at": interval.ends_at.isoformat(),
            "pv_energy_wh": interval.pv_energy_wh,
            "evidence_type": interval.evidence_type,
            "confidence": interval.confidence,
            "conversion_method_version": (
                interval.conversion_method_version
            ),
        }
        for interval in (
            pv_timeline.intervals
            if pv_timeline is not None
            else ()
        )
    ]
    payload = {
        "strategy_id": bundle.snapshot.strategy_id,
        "user_objective_profile": (
            {
                "profile_id": profile.profile_id,
                "version": profile.version,
                "cost_optimization_weight": profile.cost_optimization_weight,
                "self_consumption_weight": profile.self_consumption_weight,
                "reserve_availability_weight": profile.reserve_availability_weight,
                "trading_enabled": profile.trading_enabled,
                "adaptive_priority_enabled": profile.adaptive_priority_enabled,
            }
            if (profile := bundle.snapshot.user_objective_profile) is not None
            else None
        ),
        "household_planning_regime": (
            {
                "regime_id": regime.regime_id,
                "regime": regime.regime,
                "objective_order": regime.objective_order,
                "reason": regime.reason,
                "forecast_confidence": regime.forecast_confidence,
                "cumulative_forecast_energy_wh": (
                    regime.cumulative_forecast_energy_wh
                ),
                "cumulative_actual_energy_wh": (
                    regime.cumulative_actual_energy_wh
                ),
                "deviation_energy_wh": regime.deviation_energy_wh,
                "deviation_percent": regime.deviation_percent,
                "underperformance_duration_seconds": (
                    regime.underperformance_duration_seconds
                ),
                "evidence_ids": regime.evidence_ids,
                "method_version": regime.method_version,
            }
            if (regime := bundle.snapshot.household_planning_regime) is not None
            else None
        ),
        "horizon_end": (
            bundle.snapshot.horizon_end.isoformat() if bundle.snapshot.horizon_end else None
        ),
        "facts": facts,
        "price_points": price_points,
        "pv_energy_intervals": pv_energy_intervals,
        "storage_mode_capability_evidence": (
            {
                "current_vendor_mode": mode_evidence.current_vendor_mode,
                "status": mode_evidence.status,
                "unavailable_reason": mode_evidence.unavailable_reason,
                "usable_vendor_modes": mode_evidence.usable_vendor_modes,
                "excluded_dynamic_vendor_modes": (
                    mode_evidence.excluded_dynamic_vendor_modes
                ),
                "method_version": mode_evidence.method_version,
            }
            if (mode_evidence := bundle.snapshot.storage_mode_capability_evidence)
            is not None
            else None
        ),
        "storage_mode_control_provenance": (
            {
                "status": mode_provenance.status,
                "observed_vendor_mode": mode_provenance.observed_vendor_mode,
                "observed_at": mode_provenance.observed_at.isoformat(),
                "last_planner_vendor_mode": (
                    mode_provenance.last_planner_vendor_mode
                ),
                "last_planner_application_id": (
                    mode_provenance.last_planner_application_id
                ),
                "manual_override_active": (
                    mode_provenance.manual_override_active
                ),
                "transition_reason": mode_provenance.transition_reason,
                "reset_id": mode_provenance.reset_id,
            }
            if (
                mode_provenance := (
                    bundle.snapshot.storage_mode_control_provenance
                )
            )
            is not None
            else None
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _should_run_cycle(
    previous_signature: str | None,
    bundle: PlanningInputBundle,
) -> bool:
    """Return whether a fresh Planning Input bundle requires a canonical run."""
    if previous_signature is None:
        return True
    return _planning_input_signature(bundle) != previous_signature


def _run_live_cycle(
    *,
    previous_signature: str | None,
    bundle: PlanningInputBundle,
    execute: Any,
) -> str:
    """Execute one changed-input cycle and return the committed input signature."""
    if not _should_run_cycle(previous_signature, bundle):
        assert previous_signature is not None
        return previous_signature

    execute(bundle)
    return _planning_input_signature(bundle)


def _poll_live_cycle(
    *,
    previous_signature: str | None,
    load_bundle: Any,
    execute: Any,
    prepare_bundle: (
        Callable[
            [PlanningInputBundle],
            tuple[PlanningInputBundle, Any],
        ]
        | None
    ) = None,
    persist_observation: (
        Callable[[HouseholdLoadObservation], None] | None
    ) = None,
) -> str:
    """Load fresh Planning Input and execute only when decision input changed."""
    bundle = load_bundle()
    observation = bundle.household_load_observation
    if persist_observation is not None and observation is not None:
        try:
            persist_observation(observation)
        except OSError as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_household_load_history_unavailable",
                        "error": type(exc).__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )

    preparation_diagnostics: Any = None
    if prepare_bundle is not None:
        bundle, preparation_diagnostics = prepare_bundle(bundle)

    if prepare_bundle is not None:

        def execute_prepared(
            prepared_bundle: PlanningInputBundle,
        ) -> None:
            execute(
                prepared_bundle,
                preparation_diagnostics,
            )

        return _run_live_cycle(
            previous_signature=previous_signature,
            bundle=bundle,
            execute=execute_prepared,
        )

    return _run_live_cycle(
        previous_signature=previous_signature,
        bundle=bundle,
        execute=execute,
    )


def _project_cumulative_pv_evidence(
    evidence: PVCumulativeEvidence | None,
) -> dict[str, Any]:
    if evidence is None:
        return {
            "pv_cumulative_evidence_status": "not_available",
            "pv_interval_deviations": [],
        }
    return {
        "pv_cumulative_evidence_status": "available",
        "pv_cumulative_evidence_id": evidence.evidence_id,
        "pv_cumulative_coverage_status": evidence.coverage_status,
        "pv_cumulative_starts_at": (
            evidence.starts_at.isoformat()
            if evidence.starts_at is not None
            else None
        ),
        "pv_cumulative_ends_at": (
            evidence.ends_at.isoformat()
            if evidence.ends_at is not None
            else None
        ),
        "pv_cumulative_evaluated_at": evidence.evaluated_at.isoformat(),
        "pv_cumulative_closed_interval_count": (
            evidence.closed_interval_count
        ),
        "pv_cumulative_assessed_interval_count": (
            evidence.assessed_interval_count
        ),
        "pv_cumulative_gap_interval_count": evidence.gap_interval_count,
        "pv_cumulative_coverage_ratio": evidence.coverage_ratio,
        "pv_cumulative_forecast_central_energy_wh": (
            evidence.forecast_central_energy_wh
        ),
        "pv_cumulative_actual_energy_wh": evidence.actual_energy_wh,
        "pv_cumulative_net_deviation_energy_wh": (
            evidence.net_deviation_energy_wh
        ),
        "pv_cumulative_absolute_net_deviation_energy_wh": (
            evidence.absolute_net_deviation_energy_wh
        ),
        "pv_cumulative_total_absolute_interval_deviation_energy_wh": (
            evidence.total_absolute_interval_deviation_energy_wh
        ),
        "pv_cumulative_deviation_percent": evidence.deviation_percent,
        "pv_cumulative_percentage_status": evidence.percentage_status,
        "pv_cumulative_forecast_lower_energy_wh": (
            evidence.forecast_lower_energy_wh
        ),
        "pv_cumulative_forecast_upper_energy_wh": (
            evidence.forecast_upper_energy_wh
        ),
        "pv_cumulative_forecast_range_status": (
            evidence.forecast_range_status
        ),
        "pv_cumulative_range_assessment": evidence.range_assessment,
        "pv_cumulative_range_distance_wh": evidence.range_distance_wh,
        "pv_cumulative_range_assessed_interval_count": (
            evidence.range_assessed_interval_count
        ),
        "pv_cumulative_below_range_interval_count": (
            evidence.below_range_interval_count
        ),
        "pv_cumulative_within_range_interval_count": (
            evidence.within_range_interval_count
        ),
        "pv_cumulative_above_range_interval_count": (
            evidence.above_range_interval_count
        ),
        "pv_cumulative_unavailable_range_interval_count": (
            evidence.unavailable_range_interval_count
        ),
        "pv_cumulative_interval_deviation_ids": list(
            evidence.interval_deviation_ids
        ),
        "pv_cumulative_method_version": evidence.method_version,
    }


def _project_interval_pv_deviation(
    deviation: PVDeviationResult,
) -> dict[str, Any]:
    return {
        "deviation_id": deviation.deviation_id,
        "starts_at": deviation.starts_at.isoformat(),
        "ends_at": deviation.ends_at.isoformat(),
        "forecast_interval_id": deviation.forecast_interval_id,
        "actual_interval_id": deviation.actual_interval_id,
        "forecast_central_energy_wh": (
            deviation.forecast_central_energy_wh
        ),
        "forecast_lower_energy_wh": deviation.forecast_lower_energy_wh,
        "forecast_upper_energy_wh": deviation.forecast_upper_energy_wh,
        "actual_energy_wh": deviation.actual_energy_wh,
        "deviation_energy_wh": deviation.deviation_energy_wh,
        "absolute_deviation_energy_wh": (
            deviation.absolute_deviation_energy_wh
        ),
        "deviation_percent": deviation.deviation_percent,
        "percentage_status": deviation.percentage_status,
        "direction": deviation.direction,
        "range_assessment": deviation.range_assessment,
        "range_distance_wh": deviation.range_distance_wh,
        "forecast_confidence": deviation.forecast_confidence,
        "actual_confidence": deviation.actual_confidence,
        "forecast_evidence_ids": list(deviation.forecast_evidence_ids),
        "actual_evidence_ids": list(deviation.actual_evidence_ids),
        "forecast_conversion_method_version": (
            deviation.forecast_conversion_method_version
        ),
        "actual_conversion_method_version": (
            deviation.actual_conversion_method_version
        ),
        "range_assessment_method_version": (
            deviation.range_assessment_method_version
        ),
        "evaluation_method_version": deviation.evaluation_method_version,
    }


def _with_planning_input_diagnostics(
    projection: Projection,
    bundle: PlanningInputBundle,
    *,
    pv_actual_diagnostics: LivePVActualDiagnostics | None = None,
) -> Projection:
    """Passively enrich card 1 from already assembled Planning Input data."""
    sources = [
        {
            "category": evidence.category,
            "semantic_role": evidence.semantic_role,
            "entity_id": evidence.entity_id,
            "availability": evidence.availability,
            "raw_state": evidence.raw_state,
            "raw_unit": evidence.raw_unit,
            "canonical_value": fact.value,
            "canonical_unit": fact.unit,
            "fact_id": fact.fact_id,
            "evidence_id": evidence.evidence_id,
            "mapping_version": evidence.mapping_version,
            "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
            "confidence_status": fact.confidence_status,
            "price_point_count": len(evidence.price_points),
            "error": evidence.error,
        }
        for evidence, fact in zip(bundle.evidence, bundle.facts, strict=True)
    ]
    pv_actual_attributes: dict[str, Any] = {}
    if pv_actual_diagnostics is not None:
        deviation = pv_actual_diagnostics.deviation_result
        pv_actual_attributes = {
            "pv_actual_history_status": (
                pv_actual_diagnostics.history_status
            ),
            "pv_actual_interval_status": (
                pv_actual_diagnostics.interval_status
            ),
            "pv_actual_cache_hit": (
                pv_actual_diagnostics.cache_hit
            ),
            "pv_actual_entity_id": (
                pv_actual_diagnostics.entity_id
            ),
            "pv_actual_starts_at": (
                pv_actual_diagnostics.starts_at.isoformat()
                if pv_actual_diagnostics.starts_at is not None
                else None
            ),
            "pv_actual_ends_at": (
                pv_actual_diagnostics.ends_at.isoformat()
                if pv_actual_diagnostics.ends_at is not None
                else None
            ),
            "pv_actual_lookup_starts_at": (
                pv_actual_diagnostics.lookup_starts_at.isoformat()
                if pv_actual_diagnostics.lookup_starts_at is not None
                else None
            ),
            "pv_actual_error": pv_actual_diagnostics.error,
            "pv_actual_conversion_method_version": (
                pv_actual_diagnostics.conversion_method_version
            ),
            "pv_actual_evidence_ids": list(
                pv_actual_diagnostics.actual_evidence_ids
            ),
            "pv_actual_processing_ms": (
                pv_actual_diagnostics.processing_ms
            ),
            "pv_actual_closed_forecast_count": (
                pv_actual_diagnostics.closed_forecast_count
            ),
            "pv_actual_interval_count": (
                pv_actual_diagnostics.actual_interval_count
            ),
            "pv_actual_gap_interval_count": (
                pv_actual_diagnostics.gap_interval_count
            ),
            "pv_deviation_result_count": len(
                pv_actual_diagnostics.deviation_results
            ),
            "pv_actual_gap_reason": (
                pv_actual_diagnostics.gap_reason
            ),
            "pv_actual_observation_count": (
                pv_actual_diagnostics.observation_count
            ),
            "pv_actual_first_observed_at": (
                pv_actual_diagnostics.first_observed_at.isoformat()
                if pv_actual_diagnostics.first_observed_at
                is not None
                else None
            ),
            "pv_actual_last_observed_at": (
                pv_actual_diagnostics.last_observed_at.isoformat()
                if pv_actual_diagnostics.last_observed_at
                is not None
                else None
            ),
            "pv_actual_maximum_observed_gap_seconds": (
                pv_actual_diagnostics
                .maximum_observed_gap_seconds
            ),
            "pv_actual_allowed_gap_seconds": (
                pv_actual_diagnostics.allowed_gap_seconds
            ),
            "pv_actual_history_semantics": (
                pv_actual_diagnostics.history_semantics
            ),
            "pv_actual_interruption_state": (
                pv_actual_diagnostics.interruption_state
            ),
            "pv_actual_interrupted_at": (
                pv_actual_diagnostics.interrupted_at.isoformat()
                if pv_actual_diagnostics.interrupted_at
                is not None
                else None
            ),
            "pv_deviation_status": (
                "evaluated" if deviation is not None
                else "not_available"
            ),
            "pv_deviation_id": (
                deviation.deviation_id
                if deviation is not None
                else None
            ),
            "pv_deviation_starts_at": (
                deviation.starts_at.isoformat()
                if deviation is not None
                else None
            ),
            "pv_deviation_ends_at": (
                deviation.ends_at.isoformat()
                if deviation is not None
                else None
            ),
            "pv_deviation_evaluated_at": (
                deviation.evaluated_at.isoformat()
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_interval_id": (
                deviation.forecast_interval_id
                if deviation is not None
                else None
            ),
            "pv_deviation_actual_interval_id": (
                deviation.actual_interval_id
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_energy_wh": (
                deviation.forecast_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_lower_energy_wh": (
                deviation.forecast_lower_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_central_energy_wh": (
                deviation.forecast_central_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_upper_energy_wh": (
                deviation.forecast_upper_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_range_status": (
                deviation.forecast_range_status
                if deviation is not None
                else "unavailable"
            ),
            "pv_deviation_forecast_range_source_fields": (
                list(deviation.forecast_range_source_fields)
                if deviation is not None
                else []
            ),
            "pv_deviation_forecast_range_method_version": (
                deviation.forecast_range_method_version
                if deviation is not None
                else None
            ),
            "pv_deviation_range_assessment": (
                deviation.range_assessment
                if deviation is not None
                else "unavailable"
            ),
            "pv_deviation_range_distance_wh": (
                deviation.range_distance_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_range_assessment_method_version": (
                deviation.range_assessment_method_version
                if deviation is not None
                else None
            ),
            "pv_deviation_actual_energy_wh": (
                deviation.actual_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_energy_wh": (
                deviation.deviation_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_absolute_energy_wh": (
                deviation.absolute_deviation_energy_wh
                if deviation is not None
                else None
            ),
            "pv_deviation_percent": (
                deviation.deviation_percent
                if deviation is not None
                else None
            ),
            "pv_deviation_percentage_status": (
                deviation.percentage_status
                if deviation is not None
                else None
            ),
            "pv_deviation_direction": (
                deviation.direction
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_confidence": (
                deviation.forecast_confidence
                if deviation is not None
                else None
            ),
            "pv_deviation_actual_confidence": (
                deviation.actual_confidence
                if deviation is not None
                else None
            ),
            "pv_deviation_forecast_evidence_ids": (
                list(deviation.forecast_evidence_ids)
                if deviation is not None
                else []
            ),
            "pv_deviation_actual_evidence_ids": (
                list(deviation.actual_evidence_ids)
                if deviation is not None
                else []
            ),
            "pv_deviation_forecast_conversion_method_version": (
                deviation.forecast_conversion_method_version
                if deviation is not None
                else None
            ),
            "pv_deviation_actual_conversion_method_version": (
                deviation.actual_conversion_method_version
                if deviation is not None
                else None
            ),
            "pv_deviation_evaluation_method_version": (
                deviation.evaluation_method_version
                if deviation is not None
                else None
            ),
        }
        pv_actual_attributes |= _project_cumulative_pv_evidence(
            pv_actual_diagnostics.cumulative_evidence
        )
        pv_actual_attributes["pv_interval_deviations"] = [
            _project_interval_pv_deviation(result)
            for result in pv_actual_diagnostics.deviation_results
        ]
    first = projection.cards[0]
    enriched = Card(
        first.entity_id,
        first.state,
        first.attributes
        | {
            "source_count": len(sources),
            "source_available_count": sum(
                source["availability"] == "available" for source in sources
            ),
            "horizon_end": (
                bundle.snapshot.horizon_end.isoformat() if bundle.snapshot.horizon_end else None
            ),
            "price_point_count": len(bundle.snapshot.price_points),
            "sources": sources,
        }
        | pv_actual_attributes,
    )
    return Projection(
        cards=(enriched, *projection.cards[1:]),
        projection_ms=projection.projection_ms,
    )


def _with_stage_timing_diagnostics(
    projection: Projection,
    *,
    planning_input_ms: float,
    timings: PipelineStageTimings,
) -> Projection:
    """Attach passive processing time to each canonical pipeline card."""
    stage_ms = (
        planning_input_ms,
        timings.opportunity_engine_ms,
        timings.candidate_engine_ms,
        timings.evaluation_engine_ms,
        timings.execution_plan_builder_ms,
        timings.execution_engine_ms,
        timings.execution_primitive_ms,
        timings.device_adapter_ms,
        timings.vendor_result_ms,
    )
    cards = tuple(
        Card(
            card.entity_id,
            card.state,
            card.attributes | {"processing_ms": processing_ms},
        )
        for card, processing_ms in zip(projection.cards, stage_ms, strict=True)
    )
    return Projection(cards=cards, projection_ms=projection.projection_ms)


def _price_opportunity_config(options: dict[str, Any]) -> PriceOpportunityConfig:
    low = float(options["price_low_margin_eur_per_kwh"])
    high = float(options["price_high_margin_eur_per_kwh"])
    return PriceOpportunityConfig(
        low_price_margin_eur_per_kwh=low,
        high_price_margin_eur_per_kwh=high,
        config_version=f"price-opportunity-v1:low={low:.6f}:high={high:.6f}",
    )


def _load_live_planning_input(
    token: str,
    options: dict[str, Any],
    *,
    household_load_history: HouseholdLoadHistoryStore | None = None,
) -> PlanningInputBundle:
    """Assemble live Planning Input with the configured load fallback."""
    raw_power_w = options.get("household_load_fallback_power_w", 500.0)
    try:
        fallback_power_w = float(raw_power_w)
    except (TypeError, ValueError):
        raise ValueError(
            "household_load_fallback_power_w must be a finite positive number"
        ) from None

    if not isfinite(fallback_power_w) or fallback_power_w <= 0.0:
        raise ValueError(
            "household_load_fallback_power_w must be a finite positive number"
        )

    if household_load_history is None:
        return assemble_planning_input(
            token,
            household_load_fallback_power_w=fallback_power_w,
        )

    return assemble_planning_input(
        token,
        household_load_fallback_power_w=fallback_power_w,
        household_load_observations=household_load_history.load(),
    )


def _start_web_server(
    store: WebViewStore,
) -> tuple[ThreadingHTTPServer, Thread]:
    """Start the read-only observer server beside the main pipeline loop."""
    server = create_web_server(
        store,
        host="0.0.0.0",
        port=8099,
    )
    thread = Thread(
        target=server.serve_forever,
        name="picot-v2-web-ui",
        daemon=True,
    )
    thread.start()
    return server, thread


def _grid_power_observation_interval_seconds(
    options: dict[str, Any],
) -> float:
    raw_interval = options.get(
        "grid_power_observation_interval_seconds",
        1,
    )
    if isinstance(raw_interval, bool):
        raise ValueError(
            "grid power observation interval must be a positive number"
        )
    try:
        interval = float(raw_interval)
    except (TypeError, ValueError):
        raise ValueError(
            "grid power observation interval must be a positive number"
        ) from None
    if not isfinite(interval) or interval <= 0.0:
        raise ValueError(
            "grid power observation interval must be a positive number"
        )
    return interval


def _start_fast_grid_power_observer(
    *,
    token: str,
    entity_id: str,
    interval_seconds: float,
    web_view_store: WebViewStore,
) -> Thread:
    """Start independent near-live grid-power observation."""
    observer = FastGridPowerObserver(
        binding=SourceBinding(
            category="p1",
            semantic_role="grid_power",
            entity_id=entity_id,
        ),
        read_source=HomeAssistantStateReader(token).read,
        publish=web_view_store.publish_fast_grid_power_source,
    )

    def observe() -> None:
        while True:
            observer.poll_once(polled_at=datetime.now(UTC))
            time.sleep(interval_seconds)

    thread = Thread(
        target=observe,
        name="picot-v2-fast-grid-power",
        daemon=True,
    )
    thread.start()
    return thread


def _execute_planning_bundle(
    *,
    token: str,
    price_config: PriceOpportunityConfig,
    bundle: PlanningInputBundle,
    web_view_store: WebViewStore,
    pv_actual_diagnostics: (
        LivePVActualDiagnostics | None
    ) = None,
    pv_attenuated_ranges: tuple[
        PVAttenuatedForecastRange,
        ...,
    ] = (),
    pv_sunset_source: SunsetReadResult | None = None,
    pv_sunset_local_timezone: str | None = None,
    pv_sunset_offsets: dict[str, float] | None = None,
    pv_attenuation_learning_result: (
        PVAttenuationLearningResult | None
    ) = None,
    live_pv_canary_runtime: LivePVCanaryRuntime | None = None,
    live_pv_canary_enabled: bool = False,
    live_pv_canary_target_entity: str = "",
    storage_mode_provenance_runtime: (
        LiveStorageModeProvenanceRuntime | None
    ) = None,
    canonical_execution_runtime: CanonicalExecutionRuntime | None = None,
    canonical_execution_enabled: bool = False,
) -> None:
    """Run, project, and publish one already assembled Planning Input bundle."""
    planning_input_ms = round(
        (bundle.assembly_finished_at - bundle.assembly_started_at).total_seconds() * 1000.0,
        3,
    )

    run, stage_timings = CanonicalPipeline().run_timed(
        planning_input=bundle.snapshot,
        price_opportunity_config=price_config,
        control_change_allowed=canonical_execution_enabled,
    )
    if canonical_execution_runtime is not None:
        run = canonical_execution_runtime.apply(run)
        if (
            run.vendor_result.status in {"dispatched", "already_active"}
            and run.vendor_result.planned_vendor_mode is not None
            and storage_mode_provenance_runtime is not None
        ):
            storage_mode_provenance_runtime.record_planner_application(
                run.vendor_result.planned_vendor_mode,
                applied_at=bundle.snapshot.captured_at,
                application_id=(
                    "canonical-execution:"
                    f"{run.planning_input.run_id}:"
                    f"{run.vendor_result.command_id or 'already-active'}"
                ),
            )
    planner_cycle_ms = stage_timings.canonical_total_ms
    pipeline_total_ms = round(planning_input_ms + stage_timings.canonical_total_ms, 3)

    projection = _with_planning_input_diagnostics(
        project(run),
        bundle,
        pv_actual_diagnostics=pv_actual_diagnostics,
    )
    projection = attach_pv_attenuation_runtime_diagnostics(
        projection,
        pv_attenuated_ranges,
    )
    if pv_attenuation_learning_result is not None:
        first = projection.cards[0]
        projection = Projection(
            cards=(
                Card(
                    first.entity_id,
                    first.state,
                    first.attributes
                    | project_pv_attenuation_learning_result(
                        pv_attenuation_learning_result
                    ),
                ),
                *projection.cards[1:],
            ),
            projection_ms=projection.projection_ms,
        )
    if pv_sunset_source is not None:
        if pv_sunset_local_timezone is None:
            raise ValueError(
                "pv_sunset_local_timezone is required with sunset evidence"
            )
        projection = attach_pv_sunset_runtime_diagnostics(
            projection,
            source=pv_sunset_source,
            local_timezone=pv_sunset_local_timezone,
            offsets_by_interval_id=pv_sunset_offsets or {},
        )
    projection = _with_stage_timing_diagnostics(
        projection,
        planning_input_ms=planning_input_ms,
        timings=stage_timings,
    )
    if live_pv_canary_runtime is not None:
        canary_evidence = live_pv_runtime_evidence(
            bundle,
            sampled_at=bundle.snapshot.captured_at,
        )
        if canary_evidence is None:
            canary_result = LivePVCanaryResult(
                status="blocked",
                requested_vendor_mode=None,
                reason="live_evidence_unavailable",
                normal_result=(
                    "PicoT stuurt niet omdat actuele Zendure-modus- "
                    "of batterijvermogensgegevens ontbreken."
                ),
            )
        else:
            canary_input = build_live_pv_mode_input(
                run,
                evidence=canary_evidence,
                at=bundle.snapshot.captured_at,
                live_enabled=live_pv_canary_enabled,
            )
            canary_result = live_pv_canary_runtime.apply(
                canary_input,
                target_entity=live_pv_canary_target_entity,
            )
            if (
                canary_result.status == "dispatched"
                and canary_result.requested_vendor_mode is not None
                and storage_mode_provenance_runtime is not None
            ):
                storage_mode_provenance_runtime.record_planner_application(
                    canary_result.requested_vendor_mode,
                    applied_at=bundle.snapshot.captured_at,
                    application_id=(
                        "live-pv-canary:"
                        f"{run.planning_input.run_id}:"
                        f"{bundle.snapshot.captured_at.isoformat()}"
                    ),
                )
        projection = Projection(
            cards=(
                *projection.cards,
                project_live_pv_canary_result(
                    canary_result,
                    captured_at=bundle.snapshot.captured_at,
                    live_enabled=live_pv_canary_enabled,
                ),
            ),
            projection_ms=projection.projection_ms,
        )
    serialization_started = perf_counter()
    json.dumps([asdict(card) for card in projection.cards], separators=(",", ":"))
    serialization_ms = round((perf_counter() - serialization_started) * 1000.0, 3)

    sink = HomeAssistantProjectionSink(token)
    publish_started = perf_counter()
    for card in projection.cards:
        sink.publish(card)
    publish_ms = round((perf_counter() - publish_started) * 1000.0, 3)

    sink.publish(
        Card(
            "sensor.picot_v2_diagnostic_performance",
            "ready",
            {
                "picot_version": run.planning_input.picot_version,
                "run_id": run.planning_input.run_id,
                "pipeline_total_ms": pipeline_total_ms,
                "planning_input_ms": planning_input_ms,
                "opportunity_engine_ms": stage_timings.opportunity_engine_ms,
                "candidate_engine_ms": stage_timings.candidate_engine_ms,
                "evaluation_engine_ms": stage_timings.evaluation_engine_ms,
                "execution_plan_builder_ms": stage_timings.execution_plan_builder_ms,
                "execution_engine_ms": stage_timings.execution_engine_ms,
                "execution_primitive_ms": stage_timings.execution_primitive_ms,
                "device_adapter_ms": stage_timings.device_adapter_ms,
                "vendor_result_ms": stage_timings.vendor_result_ms,
                "canonical_pipeline_02_09_ms": stage_timings.canonical_total_ms,
                "planner_cycle_ms": planner_cycle_ms,
                "diagnostic_projection_ms": projection.projection_ms,
                "serialization_ms": serialization_ms,
                "ha_publish_ms": publish_ms,
                "persistence_ms": 0.0,
                "trace_events_per_run": len(projection.cards),
                "buffer_depth": 0,
                "source_fact_count": len(bundle.facts),
                "source_available_count": sum(
                    fact.availability == "available" for fact in bundle.facts
                ),
                "observer_only": True,
            },
        )
    )

    display_price_points = tuple(
        point
        for evidence in bundle.evidence
        for point in evidence.price_points
    )
    web_view_store.publish(
        build_web_view(
            run,
            projection,
            display_price_points=display_price_points,
        )
    )

    print(
        json.dumps(
            {
                "event": "picot_v2_planning_input_ready",
                "version": run.planning_input.picot_version,
                "run_id": run.planning_input.run_id,
                "snapshot_id": run.planning_input.snapshot_id,
                "source_facts": len(bundle.facts),
                "source_available": sum(
                    fact.availability == "available" for fact in bundle.facts
                ),
                "price_points": len(bundle.snapshot.price_points),
                "opportunities": len(run.opportunities.opportunities),
                "opportunity_status": run.opportunities.detection_status,
                "pipeline_total_ms": pipeline_total_ms,
                "cards": len(projection.cards),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def main() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("Supervisor token is required")

    options = load_options()
    price_config = _price_opportunity_config(options)
    household_objective_profile = _household_objective_profile(options)
    adaptive_household_policy = _adaptive_household_policy(options)
    web_view_store = WebViewStore()
    household_load_history = HouseholdLoadHistoryStore(
        HOUSEHOLD_LOAD_HISTORY_PATH
    )
    pv_history_reader = HomeAssistantPVHistoryReader(token)
    pv_actual_cache = LivePVActualCache()
    storage_mode_provenance_runtime = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(STORAGE_MODE_PROVENANCE_PATH)
    )
    live_pv_canary_mode = str(
        options.get("live_pv_canary_mode", "observer")
    )
    if live_pv_canary_mode not in {"observer", "live"}:
        raise ValueError(
            "live_pv_canary_mode must be observer or live"
        )
    live_pv_canary_enabled = live_pv_canary_mode == "live"
    canonical_execution_mode = str(
        options.get("canonical_execution_mode", "observer")
    )
    if canonical_execution_mode not in {"observer", "live"}:
        raise ValueError(
            "canonical_execution_mode must be observer or live"
        )
    canonical_execution_enabled = canonical_execution_mode == "live"
    if canonical_execution_enabled and live_pv_canary_enabled:
        raise ValueError(
            "live_pv_canary_mode and canonical_execution_mode "
            "cannot both be live"
        )
    live_pv_canary_target_entity = str(
        options.get("zendure_mode_entity", "")
    ).strip()
    if live_pv_canary_enabled and not live_pv_canary_target_entity:
        raise ValueError("zendure_mode_entity must be explicit")
    if not live_pv_canary_target_entity:
        live_pv_canary_target_entity = (
            "input_select.unconfigured_observer_only"
        )
    live_pv_canary_runtime = LivePVCanaryRuntime(
        dispatch=HomeAssistantLivePVModeAdapter(
            token=token,
            requested_at=lambda: datetime.now(UTC),
        )
    )
    canonical_execution_runtime = CanonicalExecutionRuntime(
        dispatch=HomeAssistantCanonicalModeAdapter(
            token=token,
            requested_at=lambda: datetime.now(UTC),
        )
    )
    def reset_storage_mode_override(
        reset_id: str,
    ) -> dict[str, object]:
        provenance = (
            storage_mode_provenance_runtime.reset_current_manual_override(
                reset_at=datetime.now(UTC),
                reset_id=reset_id,
            )
        )
        return {
            "status": provenance.status,
            "reset_id": provenance.reset_id,
            "manual_override_active": provenance.manual_override_active,
        }

    web_view_store.set_storage_mode_override_reset(
        reset_storage_mode_override
    )
    pv_sunset_local_timezone = str(
        options.get("pv_local_timezone", "Europe/Amsterdam")
    ).strip()
    if not pv_sunset_local_timezone:
        raise ValueError("pv_local_timezone must be explicit")
    try:
        pv_sunset_timezone = ZoneInfo(pv_sunset_local_timezone)
    except ZoneInfoNotFoundError:
        raise ValueError(
            "pv_local_timezone must be a valid IANA timezone"
        ) from None
    pv_sunset_reader = HomeAssistantSunsetReader(token)
    pv_solar_history_reader = HomeAssistantSolarHistoryReader(token)
    pv_power_entity = str(
        options.get("pv_power_entity", "")
    ).strip()
    if not pv_power_entity:
        raise ValueError("pv_power_entity must be explicit")

    pv_installation_scope_id = str(
        options.get("pv_installation_scope_id", "pv-installation-home")
    ).strip()
    if not pv_installation_scope_id:
        raise ValueError("pv_installation_scope_id must be explicit")

    pv_attenuation_learning = (
        ObserverOnlyPVAttenuationLearningRuntime(
            forecast_basis_path=(
                PV_ATTENUATION_FORECAST_BASIS_PATH
            ),
            evidence_store=PVAttenuationEvidenceStore(
                PV_ATTENUATION_EVIDENCE_PATH
            ),
            solar_history_reader=pv_solar_history_reader.read,
            installation_scope_id=pv_installation_scope_id,
            local_timezone=pv_sunset_timezone,
            maximum_solar_age_seconds=900.0,
            forecast_mapping_version=(
                "solcast-combined-installation:v1"
            ),
            eligibility_config=PVAttenuationEligibilityConfig(
                minimum_forecast_energy_wh=100.0,
                minimum_forecast_confidence=0.3,
                minimum_actual_confidence=0.9,
                maximum_attenuation_ratio=0.7,
                minimum_preceding_tracking_ratio=0.8,
                maximum_preceding_tracking_ratio=1.2,
                minimum_distinct_days=3,
                sunset_bucket_tolerance_minutes=20.0,
                maximum_evidence_age_days=45,
                configuration_version=(
                    "pv-attenuation-eligibility-config:v1"
                ),
            ),
            aggregation_config=PVAttenuationAggregationConfig(
                sunset_bucket_width_minutes=30.0,
                minimum_sample_count=3,
                minimum_distinct_days=3,
                maximum_dispersion=0.2,
                minimum_profile_confidence=0.4,
                maximum_evidence_age_days=45,
                profile_validity_days=7,
                configuration_version=(
                    "pv-attenuation-aggregation-config:v1"
                ),
            ),
        )
    )

    raw_pv_telemetry_interval = options.get(
        "pv_power_telemetry_interval_seconds",
        options.get("telemetry_interval_seconds", 5),
    )
    try:
        pv_telemetry_interval_seconds = int(
            raw_pv_telemetry_interval
        )
    except (TypeError, ValueError):
        raise ValueError(
            "pv telemetry interval must be a positive integer"
        ) from None
    if (
        isinstance(raw_pv_telemetry_interval, bool)
        or pv_telemetry_interval_seconds <= 0
    ):
        raise ValueError(
            "pv telemetry interval must be a positive integer"
        )

    _start_web_server(web_view_store)
    grid_power_entity = str(
        options.get("p1_power_entity", "")
    ).strip()
    if grid_power_entity:
        _start_fast_grid_power_observer(
            token=token,
            entity_id=grid_power_entity,
            interval_seconds=(
                _grid_power_observation_interval_seconds(options)
            ),
            web_view_store=web_view_store,
        )
    raw_poll_interval = options.get("live_poll_interval_seconds", 60.0)
    try:
        poll_interval_seconds = float(raw_poll_interval)
    except (TypeError, ValueError):
        poll_interval_seconds = 60.0
    poll_interval_seconds = max(5.0, poll_interval_seconds)

    def load_bundle() -> PlanningInputBundle:
        return _load_live_planning_input(
            token,
            options,
            household_load_history=household_load_history,
        )

    previous_household_regime: HouseholdPlanningRegime | None = None
    household_regime_started_at: datetime | None = None

    def prepare_bundle(
        bundle: PlanningInputBundle,
    ) -> tuple[
        PlanningInputBundle,
        LivePVActualDiagnostics,
    ]:
        nonlocal previous_household_regime, household_regime_started_at
        bundle = attach_storage_mode_provenance(
            bundle,
            storage_mode_provenance_runtime,
        )
        if bundle.snapshot.pv_energy_timeline is not None:
            pv_attenuation_learning.capture_forecast_basis(
                timeline=bundle.snapshot.pv_energy_timeline,
                captured_at=bundle.snapshot.captured_at,
            )
        prepared_bundle, diagnostics = apply_latest_closed_actual_pv(
            bundle,
            entity_id=pv_power_entity,
            history_reader=pv_history_reader.read,
            cache=pv_actual_cache,
            telemetry_interval_seconds=(
                pv_telemetry_interval_seconds
            ),
        )
        captured_at = prepared_bundle.snapshot.captured_at
        previous_duration_seconds = (
            int((captured_at - household_regime_started_at).total_seconds())
            if household_regime_started_at is not None
            else 0
        )
        prepared_bundle = _attach_live_household_objectives(
            prepared_bundle,
            diagnostics,
            profile=household_objective_profile,
            policy=adaptive_household_policy,
            previous_regime=previous_household_regime,
            previous_regime_duration_seconds=max(0, previous_duration_seconds),
        )
        current_regime = prepared_bundle.snapshot.household_planning_regime
        if current_regime is not None and (
            previous_household_regime is None
            or current_regime.regime != previous_household_regime.regime
        ):
            household_regime_started_at = captured_at
        previous_household_regime = current_regime
        return prepared_bundle, diagnostics

    def execute(
        bundle: PlanningInputBundle,
        pv_actual_diagnostics: LivePVActualDiagnostics,
    ) -> None:
        timeline = bundle.snapshot.pv_energy_timeline
        pv_sunset_source = pv_sunset_reader.read(
            local_timezone=pv_sunset_timezone
        )
        pv_sunset_offsets = (
            derive_pv_sunset_offsets(
                timeline=timeline,
                sunsets_by_local_date=dict(
                    pv_sunset_source.sunsets_by_local_date
                ),
                projected_at=bundle.snapshot.captured_at,
            )
            if (
                timeline is not None
                and pv_sunset_source.status == "available"
            )
            else {}
        )
        pv_attenuation_learning_result = (
            pv_attenuation_learning.evaluate_closed_actuals(
                actual_intervals=tuple(
                    interval
                    for interval in timeline.intervals
                    if interval.evidence_type == "ACTUAL"
                ),
                evaluated_at=bundle.snapshot.captured_at,
            )
            if timeline is not None
            else None
        )
        pv_attenuated_ranges = (
            derive_live_pv_attenuation_ranges(
                installation_scope_id=pv_installation_scope_id,
                timeline=timeline,
                profile=(
                    pv_attenuation_learning_result.profile
                    if pv_attenuation_learning_result is not None
                    else None
                ),
                minutes_from_sunset_by_interval_id=pv_sunset_offsets,
                projected_at=bundle.snapshot.captured_at,
            )
            if timeline is not None
            else ()
        )
        _execute_planning_bundle(
            token=token,
            price_config=price_config,
            bundle=bundle,
            web_view_store=web_view_store,
            pv_actual_diagnostics=pv_actual_diagnostics,
            pv_attenuated_ranges=pv_attenuated_ranges,
            pv_sunset_source=pv_sunset_source,
            pv_sunset_local_timezone=pv_sunset_local_timezone,
            pv_sunset_offsets=pv_sunset_offsets,
            pv_attenuation_learning_result=(
                pv_attenuation_learning_result
            ),
            live_pv_canary_runtime=live_pv_canary_runtime,
            live_pv_canary_enabled=live_pv_canary_enabled,
            live_pv_canary_target_entity=(
                live_pv_canary_target_entity
            ),
            storage_mode_provenance_runtime=(
                storage_mode_provenance_runtime
            ),
            canonical_execution_runtime=canonical_execution_runtime,
            canonical_execution_enabled=canonical_execution_enabled,
        )

    previous_signature: str | None = None
    while True:
        previous_signature = _poll_live_cycle(
            previous_signature=previous_signature,
            load_bundle=load_bundle,
            prepare_bundle=prepare_bundle,
            execute=execute,
            persist_observation=household_load_history.append,
        )
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    main()
