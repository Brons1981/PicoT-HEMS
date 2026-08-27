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
from functools import partial
from hashlib import sha256
from http.server import ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.market_daily_planner import MarketTradingPolicy
from picot.v2.candidate_engine import CandidateEngine, CandidateInputError
from picot.v2.canonical_execution_runtime import (
    CanonicalExecutionRuntime,
    HomeAssistantCanonicalModeAdapter,
)
from picot.v2.contracts import CanonicalPipelineRun, PlanningInputSnapshot
from picot.v2.daily_pv_basis import (
    DailyPVBasisDecision,
    apply_daily_measured_pv_basis,
)
from picot.v2.fast_grid_power_observation import FastGridPowerObserver
from picot.v2.financial_result_ledger import FinancialResultLedger
from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.household_objective_input import attach_household_objectives
from picot.v2.household_planning_regime import (
    AdaptiveHouseholdObjectivePolicy,
    HouseholdPlanningRegime,
    UserObjectiveProfile,
)
from picot.v2.independent_daily_dashboard import (
    build_daily_observer_dashboard_view,
)
from picot.v2.independent_daily_observer_runtime import (
    DailyObserverResultStore,
    DailyObserverRuntimeOutcome,
    IndependentDailyObserverRuntime,
    IndependentDailyObserverWorker,
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
from picot.v2.market_daily_dashboard import build_market_daily_runtime_view
from picot.v2.market_daily_runtime import (
    MarketDailyExecutionRuntime,
    MarketDailyPlannerRuntime,
    MarketDailyPlannerWorker,
    MarketDailyRuntimeOutcome,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline, PipelineStageTimings
from picot.v2.plan_commitment_store import (
    COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)
from picot.v2.planner_comparison_ledger import PlannerComparisonLedger
from picot.v2.planning_fallback_notifications import PlanningFallbackNotifier
from picot.v2.planning_incident_history import PlanningIncidentHistory
from picot.v2.planning_input import (
    HomeAssistantStateReader,
    HouseholdLoadObservation,
    PlanningInputBundle,
    SourceBinding,
    assemble_planning_input,
    load_options,
)
from picot.v2.power_history import (
    FINANCIAL_ANCHOR_LOOKBACK,
    HomeAssistantPowerHistoryReader,
    PowerHistoryCache,
    PowerHistoryPoint,
    PowerHistorySeries,
    PowerHistorySnapshot,
    PowerSeriesSpec,
    rebase_power_history,
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
from picot.v2.remaining_pv_storage_feasibility import (
    RemainingPVStorageFeasibility,
    derive_remaining_pv_storage_feasibility,
)
from picot.v2.storage_mode_transition_history import (
    StorageModeTransitionEvent,
    StorageModeTransitionHistoryStore,
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
STORAGE_MODE_TRANSITION_HISTORY_PATH = Path(
    "/data/picot_v2_storage_mode_transition_history.jsonl"
)
ACTIVE_PLAN_COMMITMENT_PATH = Path("/data/picot_v2_active_plan_commitments.json")
ACTIVE_PLAN_COMMITMENT_INCIDENT_PATH = Path(
    "/data/picot_v2_active_plan_commitment_incidents.jsonl"
)
PLANNING_INCIDENT_HISTORY_PATH = Path(
    "/data/picot_v2_planning_incident_history.jsonl"
)
DAILY_OBSERVER_LATEST_PATH = Path(
    "/data/picot_v2_daily_observer_latest.json"
)
DAILY_OBSERVER_HISTORY_PATH = Path(
    "/data/picot_v2_daily_observer_history.jsonl"
)
PLANNER_COMPARISON_STATE_PATH = Path(
    "/data/picot_v2_planner_comparison_state.json"
)
PLANNER_COMPARISON_HISTORY_PATH = Path(
    "/data/picot_v2_planner_comparison_history.jsonl"
)
FINANCIAL_RESULT_STATE_PATH = Path("/data/picot_v2_financial_results.json")
MARKET_DAILY_LATEST_PATH = Path(
    "/data/picot_v2_market_daily_latest.json"
)


def _save_market_daily_diagnostics(
    path: Path,
    market_view: dict[str, object],
) -> None:
    """Atomically retain the current complete MEP diagnostic projection."""
    encoded = json.dumps(market_view, separators=(",", ":"), sort_keys=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def _winning_plan_confidence(run: CanonicalPipelineRun) -> float | None:
    winning_id = run.evaluation.winning_candidate_id
    for outcome in run.outcomes.outcomes:
        if outcome.candidate_id == winning_id:
            return outcome.confidence
    return None


def _append_storage_mode_transition(
    store: StorageModeTransitionHistoryStore | None,
    *,
    previous_vendor_mode: str,
    requested_vendor_mode: str,
    source: str,
    reason: str,
    confidence: float | None,
    run_id: str,
    snapshot_id: str,
    evaluation_id: str | None,
    plan_id: str | None,
    application_id: str,
    occurred_at: datetime,
) -> None:
    if store is None or previous_vendor_mode == requested_vendor_mode:
        return
    event_seed = f"{application_id}|{previous_vendor_mode}|{requested_vendor_mode}"
    store.append(
        StorageModeTransitionEvent(
            event_id=f"storage-mode-transition-{sha256(event_seed.encode()).hexdigest()[:16]}",
            occurred_at=occurred_at,
            previous_vendor_mode=previous_vendor_mode,
            requested_vendor_mode=requested_vendor_mode,
            source=source,
            reason=reason,
            confidence=confidence,
            run_id=run_id,
            snapshot_id=snapshot_id,
            evaluation_id=evaluation_id,
            plan_id=plan_id,
            application_id=application_id,
        )
    )


def _dashboard_power_history_specs(
    options: dict[str, Any],
) -> tuple[PowerSeriesSpec, ...]:
    specs: list[PowerSeriesSpec] = []
    configured = (
        (
            "pv",
            "pv_generation",
            "pv_power_entity",
            "identity",
        ),
        (
            "grid-import",
            "grid_import",
            "p1_power_entity",
            "positive",
        ),
        (
            "grid-export",
            "grid_export",
            "p1_power_entity",
            "negative_magnitude",
        ),
        (
            "battery-discharge",
            "battery_discharge",
            "zendure_power_to_house_entity",
            "identity",
        ),
        (
            "battery-charge",
            "battery_charge",
            "zendure_power_from_house_entity",
            "identity",
        ),
    )
    for series_id, role, option_name, transform in configured:
        entity_id = str(options.get(option_name, "")).strip()
        if entity_id:
            specs.append(
                PowerSeriesSpec(
                    series_id=series_id,
                    role=role,
                    entity_id=entity_id,
                    transform=transform,
                )
            )
    return tuple(specs)


def _attach_household_power_history(
    snapshot: PowerHistorySnapshot,
    observations: tuple[HouseholdLoadObservation, ...],
) -> PowerHistorySnapshot:
    ordered = tuple(sorted(observations, key=lambda item: item.sampled_at))
    anchor = next(
        (
            observation
            for observation in reversed(ordered)
            if observation.sampled_at <= snapshot.starts_at
        ),
        None,
    )
    bounded = (
        *((anchor,) if anchor is not None else ()),
        *(
            observation
            for observation in ordered
            if snapshot.starts_at < observation.sampled_at <= snapshot.ends_at
        ),
    )
    points = tuple(
        PowerHistoryPoint(
            sampled_at=observation.sampled_at,
            power_w=observation.power_w,
            evidence_id=(
                observation.evidence_ids[0]
                if observation.evidence_ids
                else f"household-load:{observation.sampled_at.isoformat()}"
            ),
        )
        for observation in bounded
    )
    household = PowerHistorySeries(
        series_id="household-load",
        role="household_load",
        source_entity_id="picot:household-load-observation",
        transform="identity",
        points=points,
        history_semantics="sampled_linear",
    )
    series = (*snapshot.series, household)
    return replace(
        snapshot,
        status=(
            "available"
            if any(item.points for item in series)
            else snapshot.status
        ),
        series=series,
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
        minimum_conservative_pv_storage_margin_wh=float(
            options.get(
                "household_minimum_conservative_pv_storage_margin_wh",
                500.0,
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
    storage_feasibility: RemainingPVStorageFeasibility | None = None,
) -> PlanningInputBundle:
    cumulative = diagnostics.cumulative_evidence
    deviations = diagnostics.deviation_results
    timeline = bundle.snapshot.pv_energy_timeline
    future_intervals = tuple(
        interval
        for interval in (timeline.intervals if timeline is not None else ())
        if interval.evidence_type == "FORECAST"
        and interval.ends_at > bundle.snapshot.captured_at
    )
    future_weights = tuple(
        max(interval.pv_energy_wh, 1.0) for interval in future_intervals
    )
    if future_intervals:
        forecast_confidence = sum(
            interval.confidence * weight
            for interval, weight in zip(
                future_intervals,
                future_weights,
                strict=True,
            )
        ) / sum(future_weights)
        future_confidence_evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for interval in future_intervals
                for evidence_id in interval.forecast_evidence_ids
            )
        )
        forecast_confidence_method_version = (
            "remaining-pv-energy-weighted-source-confidence:v1"
        )
        forecast_confidence_available = True
    else:
        # The numeric field remains for wire compatibility; availability is the
        # authority and prevents this sentinel from becoming planning evidence.
        forecast_confidence = 0.0
        future_confidence_evidence_ids = ()
        forecast_confidence_method_version = (
            "remaining-pv-confidence-unavailable:v1"
        )
        forecast_confidence_available = False
    if cumulative is None or cumulative.assessed_interval_count == 0:
        forecast_energy_wh = 0.0
        actual_energy_wh = 0.0
        duration_seconds = 0
        evidence_ids: tuple[str, ...] = (
            f"{profile.profile_id}:{profile.version}:pv-deviation-unavailable",
        )
    else:
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
        evidence_ids=tuple(
            dict.fromkeys(
                (
                    *evidence_ids,
                    *future_confidence_evidence_ids,
                    *(
                        storage_feasibility.evidence_ids
                        if storage_feasibility is not None
                        else ()
                    ),
                )
            )
        ),
        previous_regime=previous_regime,
        previous_regime_duration_seconds=previous_regime_duration_seconds,
        recovery_duration_seconds=_rolling_pv_recovery_seconds(deviations),
        overperformance_duration_seconds=_rolling_pv_direction_seconds(
            deviations,
            direction="above_forecast",
        ),
        remaining_storage_need_wh=(
            storage_feasibility.remaining_storage_need_wh
            if storage_feasibility is not None
            else None
        ),
        conservative_remaining_pv_surplus_wh=(
            storage_feasibility.conservative_remaining_pv_surplus_wh
            if storage_feasibility is not None
            else None
        ),
        remaining_pv_storage_margin_wh=(
            storage_feasibility.margin_wh
            if storage_feasibility is not None
            else None
        ),
        storage_target_required_by=(
            storage_feasibility.required_by
            if storage_feasibility is not None
            else None
        ),
        forecast_confidence_method_version=(
            forecast_confidence_method_version
        ),
        forecast_confidence_available=forecast_confidence_available,
    )
    return replace(bundle, snapshot=snapshot)

def _planning_input_signature(
    bundle: PlanningInputBundle,
    *,
    retain_active_commitment: bool = True,
) -> str:
    """Return a stable signature for decision-relevant Planning Input content."""
    active_commitments = bundle.snapshot.active_plan_commitments
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
    if active_commitments and retain_active_commitment:
        # ADR-034: raw telemetry and rolling forecasts are plan progress while
        # an accepted execution commitment is active. Hard authority,
        # capability and completion facts remain decision-relevant below.
        facts = []
        price_points = []
        pv_energy_intervals = []
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
                "forecast_confidence_method_version": (
                    regime.forecast_confidence_method_version
                ),
                "forecast_confidence_available": (
                    regime.forecast_confidence_available
                ),
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
            if not active_commitments
            and (regime := bundle.snapshot.household_planning_regime) is not None
            else None
        ),
        "horizon_end": (
            bundle.snapshot.horizon_end.isoformat()
            if bundle.snapshot.horizon_end and not active_commitments
            else None
        ),
        "facts": facts,
        "price_points": price_points,
        "pv_energy_intervals": pv_energy_intervals,
        "storage_mode_capability_evidence": (
            {
                "current_vendor_mode": (
                    None
                    if active_commitments
                    else mode_evidence.current_vendor_mode
                ),
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
                "observed_vendor_mode": (
                    None
                    if active_commitments
                    else mode_provenance.observed_vendor_mode
                ),
                "observed_at": (
                    None
                    if active_commitments
                    else mode_provenance.observed_at.isoformat()
                ),
                "last_planner_vendor_mode": (
                    None
                    if active_commitments
                    else mode_provenance.last_planner_vendor_mode
                ),
                "last_planner_application_id": (
                    None
                    if active_commitments
                    else mode_provenance.last_planner_application_id
                ),
                "manual_override_active": (
                    mode_provenance.manual_override_active
                ),
                "transition_reason": (
                    None
                    if active_commitments
                    else mode_provenance.transition_reason
                ),
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
        "active_plan_commitments": [
            {
                "execution_scope_id": item.execution_scope_id,
                "plan_id": item.plan_id,
                "plan_revision": item.plan_revision,
                "primitive": item.primitive,
                "source_policy": item.source_policy,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
                "target_energy_wh": item.target_energy_wh,
                "execution_phase": (
                    "scheduled"
                    if bundle.snapshot.captured_at < item.starts_at
                    else "active"
                ),
            }
            for item in bundle.snapshot.active_plan_commitments
        ],
        "active_commitment_targets_reached": [
            {
                "execution_scope_id": commitment.execution_scope_id,
                "reached": any(
                    state.execution_scope_id == commitment.execution_scope_id
                    and state.current_stored_energy_wh + 1e-6
                    >= commitment.target_energy_wh
                    for state in bundle.snapshot.current_storage_states
                ),
            }
            for commitment in active_commitments
        ],
        "bms_calibration": (
            {
                "status": calibration.status,
                "active": calibration.active,
            }
            if (calibration := bundle.snapshot.bms_calibration_evidence)
            is not None
            else None
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _observer_input_signature(bundle: PlanningInputBundle) -> str:
    """Track slow planning inputs independently from execution commitments.

    Instantaneous power telemetry is intentionally excluded: it is published
    live through the dashboard overlay and must not start a full daily
    simulation on every poll. Availability changes remain relevant.
    """
    live_power_roles = {
        "grid_power",
        "pv_power",
        "storage_power_signed",
        "storage_power_charge",
        "storage_power_discharge",
    }
    observer_facts = tuple(
        fact
        for fact in bundle.facts
        if fact.semantic_role not in live_power_roles
        or fact.availability != "available"
    )
    return _planning_input_signature(
        replace(bundle, facts=observer_facts),
        retain_active_commitment=False,
    )


def _restore_active_plan_commitments(
    snapshot: PlanningInputSnapshot,
    store: ActivePlanCommitmentStore,
) -> PlanningInputSnapshot:
    restored = []
    capabilities = (
        snapshot.capability_snapshot_set.capabilities
        if snapshot.capability_snapshot_set is not None
        else ()
    )
    for state in snapshot.current_storage_states:
        commitment = store.load(state.execution_scope_id)
        if commitment is None:
            continue
        if commitment.ends_at <= snapshot.captured_at:
            store.clear(commitment.execution_scope_id)
            store.record_recovery_rejection("expired_at_restart")
            continue
        if commitment.selection_method_version != COMMITMENT_METHOD_VERSION:
            store.clear(commitment.execution_scope_id)
            store.record_recovery_rejection(
                "legacy_commitment_requires_household_replan"
            )
            continue
        capability = next(
            (
                item
                for item in capabilities
                if item.execution_scope_id == commitment.execution_scope_id
                and item.capability_id == state.capability_id
            ),
            None,
        )
        if (
            capability is None
            or commitment.primitive
            not in {item.value for item in capability.supported_primitives}
            or capability.availability.value != "available"
            or capability.health.value != "healthy"
        ):
            store.clear(commitment.execution_scope_id)
            store.record_recovery_rejection(
                "capability_invalid_at_restart"
            )
            continue
        restored.append(commitment)
    return replace(snapshot, active_plan_commitments=tuple(restored))


def _should_run_cycle(
    previous_signature: str | None,
    bundle: PlanningInputBundle,
) -> bool:
    """Return whether a fresh Planning Input bundle requires a canonical run."""
    if previous_signature is None:
        return True
    return _planning_input_signature(bundle) != previous_signature


def _reset_storage_mode_override_and_request_replan(
    *,
    runtime: Any,
    replan_requested: Event,
    reset_id: str,
    reset_at: datetime,
) -> dict[str, object]:
    """Clear a manual mode override and immediately wake the live planner."""
    provenance = runtime.reset_current_manual_override(
        reset_at=reset_at,
        reset_id=reset_id,
    )
    replan_requested.set()
    return {
        "status": provenance.status,
        "reset_id": provenance.reset_id,
        "manual_override_active": provenance.manual_override_active,
        "replan_requested": True,
    }


def _run_live_cycle(
    *,
    previous_signature: str | None,
    bundle: PlanningInputBundle,
    execute: Any,
    refresh_unchanged: Any = None,
) -> str:
    """Execute one changed-input cycle and return the committed input signature."""
    if not _should_run_cycle(previous_signature, bundle):
        assert previous_signature is not None
        if refresh_unchanged is not None:
            refresh_unchanged(bundle)
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
    refresh_unchanged: Callable[[PlanningInputBundle], None] | None = None,
    advance_clock_boundaries: (
        Callable[[PlanningInputBundle], None] | None
    ) = None,
    observe: Callable[[PlanningInputBundle], None] | None = None,
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

    if advance_clock_boundaries is not None:
        advance_clock_boundaries(bundle)

    if observe is not None:
        observe(bundle)

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
            refresh_unchanged=refresh_unchanged,
        )

    return _run_live_cycle(
        previous_signature=previous_signature,
        bundle=bundle,
        execute=execute,
        refresh_unchanged=refresh_unchanged,
    )


def _wait_for_poll_or_reset(
    reset_requested: Event,
    timeout_seconds: float,
) -> None:
    """Wait interruptibly while preserving the runtime's testable clock boundary."""

    deadline = time.monotonic() + timeout_seconds
    while not reset_requested.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return
        time.sleep(min(0.25, remaining))


class PlanningResetBarrier:
    """Serialize reset with a Planner Run and expose its reset generation."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def run_cycle(self, cycle: Callable[[], Any]) -> Any:
        """Prevent a reset from acknowledging halfway through this cycle."""

        with self._lock:
            return cycle()

    def reset(self, clear_state: Callable[[], Any]) -> tuple[int, Any]:
        """Clear state after any older cycle and advance the durable boundary."""

        with self._lock:
            result = clear_state()
            self._generation += 1
            return self._generation, result


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


def _planning_input_sources(
    bundle: PlanningInputBundle,
) -> list[dict[str, object]]:
    return [
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


def _with_planning_input_diagnostics(
    projection: Projection,
    bundle: PlanningInputBundle,
    *,
    pv_actual_diagnostics: LivePVActualDiagnostics | None = None,
    daily_pv_basis_decision: DailyPVBasisDecision | None = None,
) -> Projection:
    """Passively enrich card 1 from already assembled Planning Input data."""
    sources = _planning_input_sources(bundle)
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
    if daily_pv_basis_decision is not None:
        pv_actual_attributes |= {
            "daily_pv_forecast_basis": daily_pv_basis_decision.basis,
            "daily_pv_forecast_basis_reason": daily_pv_basis_decision.reason,
            "daily_pv_tracking_ratio": daily_pv_basis_decision.tracking_ratio,
            "daily_pv_recent_tracking_ratio": (
                daily_pv_basis_decision.recent_tracking_ratio
            ),
            "daily_pv_assessed_interval_count": (
                daily_pv_basis_decision.assessed_interval_count
            ),
            "daily_pv_adjusted_interval_count": (
                daily_pv_basis_decision.adjusted_interval_count
            ),
            "daily_pv_basis_evidence_id": daily_pv_basis_decision.evidence_id,
            "daily_pv_basis_method_version": (
                daily_pv_basis_decision.method_version
            ),
        }
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

    raw_confidence = options.get("household_load_fallback_confidence", 0.5)
    try:
        fallback_confidence = float(raw_confidence)
    except (TypeError, ValueError):
        raise ValueError(
            "household_load_fallback_confidence must be greater than 0 and at most 1"
        ) from None

    if (
        not isfinite(fallback_confidence)
        or not 0.0 < fallback_confidence <= 1.0
    ):
        raise ValueError(
            "household_load_fallback_confidence must be greater than 0 and at most 1"
        )

    if household_load_history is None:
        return assemble_planning_input(
            token,
            household_load_fallback_power_w=fallback_power_w,
            household_load_fallback_confidence=fallback_confidence,
        )

    return assemble_planning_input(
        token,
        household_load_fallback_power_w=fallback_power_w,
        household_load_fallback_confidence=fallback_confidence,
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
    power_history: PowerHistorySnapshot | None = None,
    power_history_read_ms: float = 0.0,
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
    storage_mode_transition_history: (
        StorageModeTransitionHistoryStore | None
    ) = None,
    canonical_execution_runtime: CanonicalExecutionRuntime | None = None,
    canonical_execution_enabled: bool = False,
    planning_fallback_notifier: PlanningFallbackNotifier | None = None,
    planning_incident_history: PlanningIncidentHistory | None = None,
    independent_daily_observer_worker: (
        IndependentDailyObserverWorker | None
    ) = None,
    independent_daily_snapshot: PlanningInputSnapshot | None = None,
    daily_pv_basis_decision: DailyPVBasisDecision | None = None,
    market_daily_planner_worker: MarketDailyPlannerWorker | None = None,
    planner_comparison_ledger: PlannerComparisonLedger | None = None,
    financial_result_ledger: FinancialResultLedger | None = None,
    micro_charge_suppression_fraction: float = 0.01,
) -> None:
    """Run, project, and publish one already assembled Planning Input bundle."""
    planning_input_ms = round(
        (bundle.assembly_finished_at - bundle.assembly_started_at).total_seconds() * 1000.0,
        3,
    )

    run, stage_timings = CanonicalPipeline(
        micro_charge_suppression_fraction=micro_charge_suppression_fraction,
    ).run_timed(
        planning_input=bundle.snapshot,
        price_opportunity_config=price_config,
        control_change_allowed=canonical_execution_enabled,
    )
    if independent_daily_observer_worker is not None:
        independent_daily_observer_worker.submit(
            independent_daily_snapshot or bundle.snapshot
        )
    if canonical_execution_runtime is not None:
        run = canonical_execution_runtime.apply(run)
        if (
            run.vendor_result.status in {"dispatched", "already_active"}
            and run.vendor_result.planned_vendor_mode is not None
            and storage_mode_provenance_runtime is not None
        ):
            application_id = (
                "canonical-execution:"
                f"{run.planning_input.run_id}:"
                f"{run.vendor_result.command_id or 'already-active'}"
            )
            provenance = storage_mode_provenance_runtime.record_planner_application(
                run.vendor_result.planned_vendor_mode,
                applied_at=bundle.snapshot.captured_at,
                application_id=application_id,
            )
            if run.vendor_result.status == "dispatched":
                _append_storage_mode_transition(
                    storage_mode_transition_history,
                    previous_vendor_mode=provenance.observed_vendor_mode,
                    requested_vendor_mode=run.vendor_result.planned_vendor_mode,
                    source="canonical_execution",
                    reason=run.evaluation.reason,
                    confidence=_winning_plan_confidence(run),
                    run_id=run.planning_input.run_id,
                    snapshot_id=run.planning_input.snapshot_id,
                    evaluation_id=run.evaluation.evaluation_id,
                    plan_id=(
                        run.execution_plan_set.plans[0].plan_id
                        if run.execution_plan_set.plans
                        else None
                    ),
                    application_id=application_id,
                    occurred_at=bundle.snapshot.captured_at,
                )
    if planning_incident_history is not None:
        try:
            planning_incident_history.record(
                bundle=bundle,
                run=run,
                runtime_diagnostics={
                    "pv_actual": (
                        asdict(pv_actual_diagnostics)
                        if pv_actual_diagnostics is not None
                        else None
                    ),
                    "sunset_source": (
                        asdict(pv_sunset_source)
                        if pv_sunset_source is not None
                        else None
                    ),
                    "pv_attenuated_ranges": [
                        asdict(item) for item in pv_attenuated_ranges
                    ],
                    "pv_attenuation_learning": (
                        asdict(pv_attenuation_learning_result)
                        if pv_attenuation_learning_result is not None
                        else None
                    ),
                },
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_planning_incident_history_error",
                        "run_id": run.planning_input.run_id,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
    if planning_fallback_notifier is not None:
        try:
            planning_fallback_notifier.update(
                token,
                run=run,
                now=bundle.snapshot.captured_at,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_planning_notification_error",
                        "run_id": run.planning_input.run_id,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
    planner_cycle_ms = stage_timings.canonical_total_ms
    pipeline_total_ms = round(planning_input_ms + stage_timings.canonical_total_ms, 3)

    projection = _with_planning_input_diagnostics(
        project(run),
        bundle,
        pv_actual_diagnostics=pv_actual_diagnostics,
        daily_pv_basis_decision=daily_pv_basis_decision,
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
                application_id = (
                    "live-pv-canary:"
                    f"{run.planning_input.run_id}:"
                    f"{bundle.snapshot.captured_at.isoformat()}"
                )
                provenance = storage_mode_provenance_runtime.record_planner_application(
                    canary_result.requested_vendor_mode,
                    applied_at=bundle.snapshot.captured_at,
                    application_id=application_id,
                )
                _append_storage_mode_transition(
                    storage_mode_transition_history,
                    previous_vendor_mode=provenance.observed_vendor_mode,
                    requested_vendor_mode=canary_result.requested_vendor_mode,
                    source="live_pv_canary",
                    reason=canary_result.reason,
                    confidence=(
                        bundle.snapshot.household_planning_regime.forecast_confidence
                        if bundle.snapshot.household_planning_regime is not None
                        else None
                    ),
                    run_id=run.planning_input.run_id,
                    snapshot_id=run.planning_input.snapshot_id,
                    evaluation_id=run.evaluation.evaluation_id,
                    plan_id=(
                        run.execution_plan_set.plans[0].plan_id
                        if run.execution_plan_set.plans
                        else None
                    ),
                    application_id=application_id,
                    occurred_at=bundle.snapshot.captured_at,
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

    display_price_points = tuple(
        point
        for evidence in bundle.evidence
        for point in evidence.price_points
    )
    web_view_build_started = perf_counter()
    web_view = build_web_view(
        run,
        projection,
        display_price_points=display_price_points,
        power_history=power_history,
        storage_mode_transitions=(
            storage_mode_transition_history.load()
            if storage_mode_transition_history is not None
            else ()
        ),
    )
    if planner_comparison_ledger is not None:
        try:
            planner_comparison_ledger.register_canonical(bundle.snapshot, web_view)
            if power_history is not None:
                planner_comparison_ledger.ingest(bundle.snapshot, power_history)
            web_view["planner_comparison_history"] = (
                planner_comparison_ledger.dashboard_view()
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_planner_comparison_error",
                        "snapshot_id": bundle.snapshot.snapshot_id,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
    if financial_result_ledger is not None and power_history is not None:
        try:
            web_view["financial_results"] = financial_result_ledger.update(
                bundle.snapshot,
                power_history,
                price_points=display_price_points,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_financial_result_error",
                        "snapshot_id": bundle.snapshot.snapshot_id,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
    web_view_build_ms = round(
        (perf_counter() - web_view_build_started) * 1000.0,
        3,
    )
    web_view_publish_started = perf_counter()
    web_view_store.publish(web_view)
    web_view_publish_ms = round(
        (perf_counter() - web_view_publish_started) * 1000.0,
        3,
    )

    sink = HomeAssistantProjectionSink(token)
    publish_started = perf_counter()
    ha_publish_status = "ready"
    try:
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
                    "opportunity_engine_ms": (
                        stage_timings.opportunity_engine_ms
                    ),
                    "candidate_engine_ms": stage_timings.candidate_engine_ms,
                    "evaluation_engine_ms": stage_timings.evaluation_engine_ms,
                    "execution_plan_builder_ms": (
                        stage_timings.execution_plan_builder_ms
                    ),
                    "execution_engine_ms": stage_timings.execution_engine_ms,
                    "execution_primitive_ms": (
                        stage_timings.execution_primitive_ms
                    ),
                    "device_adapter_ms": stage_timings.device_adapter_ms,
                    "vendor_result_ms": stage_timings.vendor_result_ms,
                    "canonical_pipeline_02_09_ms": (
                        stage_timings.canonical_total_ms
                    ),
                    "planner_cycle_ms": planner_cycle_ms,
                    "diagnostic_projection_ms": projection.projection_ms,
                    "serialization_ms": serialization_ms,
                    "ha_publish_ms": publish_ms,
                    "power_history_read_ms": power_history_read_ms,
                    "web_view_build_ms": web_view_build_ms,
                    "web_view_publish_ms": web_view_publish_ms,
                    "persistence_ms": 0.0,
                    "trace_events_per_run": len(projection.cards),
                    "buffer_depth": 0,
                    "source_fact_count": len(bundle.facts),
                    "source_available_count": sum(
                        fact.availability == "available"
                        for fact in bundle.facts
                    ),
                    "observer_only": True,
                },
            )
        )
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        publish_ms = round((perf_counter() - publish_started) * 1000.0, 3)
        ha_publish_status = "retry_next_poll"
        print(
            json.dumps(
                {
                    "event": "picot_v2_ha_projection_publish_error",
                    "run_id": run.planning_input.run_id,
                    "error": str(exc) or exc.__class__.__name__,
                    "retry": "next_poll",
                },
                separators=(",", ":"),
            ),
            flush=True,
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
                "power_history_read_ms": power_history_read_ms,
                "web_view_build_ms": web_view_build_ms,
                "web_view_publish_ms": web_view_publish_ms,
                "ha_publish_ms": publish_ms,
                "ha_publish_status": ha_publish_status,
                "cards": len(projection.cards),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _validate_live_execution_authority(
    *,
    canonical_execution_enabled: bool,
    live_pv_canary_enabled: bool,
    market_daily_execution_enabled: bool,
) -> None:
    if sum((
        canonical_execution_enabled,
        live_pv_canary_enabled,
        market_daily_execution_enabled,
    )) > 1:
        raise ValueError(
            "canonical, live PV canary and MEP execution cannot share live authority"
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
    planning_reset_requested = Event()
    planning_reset_barrier = PlanningResetBarrier()
    household_load_history = HouseholdLoadHistoryStore(
        HOUSEHOLD_LOAD_HISTORY_PATH
    )
    pv_history_reader = HomeAssistantPVHistoryReader(token)
    power_history_reader = HomeAssistantPowerHistoryReader(token)
    power_history_cache = PowerHistoryCache()
    pv_actual_cache = LivePVActualCache()
    storage_mode_provenance_runtime = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(STORAGE_MODE_PROVENANCE_PATH)
    )
    storage_mode_transition_history = StorageModeTransitionHistoryStore(
        STORAGE_MODE_TRANSITION_HISTORY_PATH
    )
    active_plan_commitment_store = ActivePlanCommitmentStore(
        ACTIVE_PLAN_COMMITMENT_PATH,
        incident_path=ACTIVE_PLAN_COMMITMENT_INCIDENT_PATH,
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
    market_daily_execution_mode = str(
        options.get("market_daily_execution_mode", "live")
    )
    if market_daily_execution_mode not in {"observer", "live"}:
        raise ValueError(
            "market_daily_execution_mode must be observer or live"
        )
    market_daily_execution_enabled = market_daily_execution_mode == "live"
    _validate_live_execution_authority(
        canonical_execution_enabled=canonical_execution_enabled,
        live_pv_canary_enabled=live_pv_canary_enabled,
        market_daily_execution_enabled=market_daily_execution_enabled,
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
        ),
        commitment_store=active_plan_commitment_store,
    )
    planning_fallback_notifier = PlanningFallbackNotifier()
    planning_incident_history = PlanningIncidentHistory(
        PLANNING_INCIDENT_HISTORY_PATH,
        local_timezone_name=str(
            options.get("pv_local_timezone", "Europe/Amsterdam")
        ).strip(),
    )
    daily_conversion_model = StorageConversionModel(
        model_id="live-observer-configured-conversion",
        charge_efficiency=float(
            options.get("daily_reference_charge_efficiency", 1.0)
        ),
        discharge_efficiency=float(
            options.get("daily_reference_discharge_efficiency", 1.0)
        ),
        evidence_ids=("addon-options:daily-reference-efficiency",),
        method_version="live-observer-configured-conversion:v1",
    )
    market_daily_conversion_model = StorageConversionModel(
        model_id="live-mep-configured-conversion",
        charge_efficiency=float(
            options.get("market_daily_charge_efficiency", 0.9110433579)
        ),
        discharge_efficiency=float(
            options.get("market_daily_discharge_efficiency", 0.9110433579)
        ),
        evidence_ids=("addon-options:market-daily-efficiency",),
        method_version="live-mep-configured-conversion:v1",
    )
    market_daily_trading_policy = MarketTradingPolicy(
        margin_fraction=(
            float(options.get("market_daily_trading_margin_percent", 10.0)) / 100.0
        ),
        wear_eur_per_export_kwh=float(
            options.get("market_daily_wear_eur_per_kwh", 0.05)
        ),
    )
    micro_charge_suppression_fraction = (
        float(options.get("micro_charge_suppression_percent", 2.0)) / 100.0
    )
    independent_daily_observer_runtime = IndependentDailyObserverRuntime(
        conversion_model=daily_conversion_model,
        micro_charge_suppression_fraction=micro_charge_suppression_fraction,
        store=DailyObserverResultStore(
            latest_path=DAILY_OBSERVER_LATEST_PATH,
            history_path=DAILY_OBSERVER_HISTORY_PATH,
        ),
    )
    planner_comparison_ledger = PlannerComparisonLedger(
        state_path=PLANNER_COMPARISON_STATE_PATH,
        history_path=PLANNER_COMPARISON_HISTORY_PATH,
        charge_efficiency=daily_conversion_model.charge_efficiency,
        discharge_efficiency=daily_conversion_model.discharge_efficiency,
    )
    financial_result_ledger = FinancialResultLedger(
        state_path=FINANCIAL_RESULT_STATE_PATH,
        wear_eur_per_discharge_kwh=market_daily_trading_policy.wear_eur_per_export_kwh,
        battery_purchase_eur=float(options.get("battery_purchase_eur", 2407.40)),
        charge_efficiency=market_daily_conversion_model.charge_efficiency,
        discharge_efficiency=market_daily_conversion_model.discharge_efficiency,
        local_timezone_name=str(options.get("pv_local_timezone", "Europe/Amsterdam")),
    )

    def publish_daily_observer_outcome(
        outcome: DailyObserverRuntimeOutcome,
    ) -> None:
        observer_view = build_daily_observer_dashboard_view(outcome)
        planner_comparison_ledger.attach_observer(observer_view)
        web_view_store.publish_daily_observer_comparison(
            observer_view
        )
        web_view_store.publish_planner_comparison_history(
            planner_comparison_ledger.dashboard_view()
        )

    def report_daily_observer_error(
        snapshot: PlanningInputSnapshot,
        exc: Exception,
    ) -> None:
        print(
            json.dumps(
                {
                    "event": "picot_v2_daily_observer_runtime_error",
                    "run_id": snapshot.run_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "error": str(exc) or exc.__class__.__name__,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    market_daily_refresh_at: datetime | None = None

    def publish_market_daily_outcome(
        outcome: MarketDailyRuntimeOutcome,
    ) -> None:
        nonlocal market_daily_refresh_at
        market_daily_refresh_at = (
            outcome.plan.current_interval_ends_at
            if outcome.plan is not None
            else None
        )
        execution = outcome.execution
        if (
            execution is not None
            and execution.status == "dispatched"
            and execution.requested_vendor_mode is not None
        ):
            application_id = (
                f"mep-execution:{outcome.run_id}:"
                f"{execution.command_id or outcome.captured_at.isoformat()}"
            )
            provenance = storage_mode_provenance_runtime.record_planner_application(
                execution.requested_vendor_mode,
                applied_at=execution.evaluated_at or outcome.captured_at,
                application_id=application_id,
            )
            _append_storage_mode_transition(
                storage_mode_transition_history,
                previous_vendor_mode=provenance.observed_vendor_mode,
                requested_vendor_mode=execution.requested_vendor_mode,
                source="mep_execution",
                reason=execution.reason,
                confidence=None,
                run_id=outcome.run_id,
                snapshot_id=outcome.snapshot_id,
                evaluation_id=None,
                plan_id=(
                    f"mep-plan:{outcome.snapshot_id}"
                ),
                application_id=application_id,
                occurred_at=execution.evaluated_at or outcome.captured_at,
            )
        market_view = build_market_daily_runtime_view(outcome)
        try:
            _save_market_daily_diagnostics(
                MARKET_DAILY_LATEST_PATH,
                market_view,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "picot_v2_market_daily_diagnostics_error",
                        "run_id": outcome.run_id,
                        "snapshot_id": outcome.snapshot_id,
                        "error": str(exc) or exc.__class__.__name__,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        web_view_store.publish_market_daily_planner(market_view)

    def report_market_daily_error(
        snapshot: PlanningInputSnapshot,
        exc: Exception,
    ) -> None:
        print(
            json.dumps(
                {
                    "event": "picot_v2_market_daily_runtime_error",
                    "run_id": snapshot.run_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "error": str(exc) or exc.__class__.__name__,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    market_daily_planner_worker = MarketDailyPlannerWorker(
        MarketDailyPlannerRuntime(
            market_daily_conversion_model,
            trading_policy=market_daily_trading_policy,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            storage_inventory_provider=(
                financial_result_ledger.storage_energy_inventory
            ),
            live_enabled=market_daily_execution_enabled,
            execution_runtime=MarketDailyExecutionRuntime(
                dispatch=HomeAssistantCanonicalModeAdapter(
                    token=token,
                    requested_at=lambda: datetime.now(UTC),
                ),
                now=lambda: datetime.now(UTC),
                commitment_store=active_plan_commitment_store,
            ),
        ),
        on_outcome=publish_market_daily_outcome,
        on_error=report_market_daily_error,
    )
    independent_daily_observer_worker = IndependentDailyObserverWorker(
        independent_daily_observer_runtime,
        on_outcome=publish_daily_observer_outcome,
        on_error=report_daily_observer_error,
        on_settled=market_daily_planner_worker.process,
    )
    web_view_store.set_diagnostic_paths(
        (
            PLANNING_INCIDENT_HISTORY_PATH,
            HOUSEHOLD_LOAD_HISTORY_PATH,
            PV_ATTENUATION_FORECAST_BASIS_PATH,
            PV_ATTENUATION_EVIDENCE_PATH,
            STORAGE_MODE_PROVENANCE_PATH,
            STORAGE_MODE_TRANSITION_HISTORY_PATH,
            ACTIVE_PLAN_COMMITMENT_PATH,
            ACTIVE_PLAN_COMMITMENT_INCIDENT_PATH,
            DAILY_OBSERVER_LATEST_PATH,
            DAILY_OBSERVER_HISTORY_PATH,
            PLANNER_COMPARISON_STATE_PATH,
            PLANNER_COMPARISON_HISTORY_PATH,
            MARKET_DAILY_LATEST_PATH,
            FINANCIAL_RESULT_STATE_PATH,
        ),
        incident_history_path=PLANNING_INCIDENT_HISTORY_PATH,
    )
    web_view_store.set_planner_stress_marker(
        lambda marker_id, note: planner_comparison_ledger.mark_stress(
            marker_id=marker_id,
            occurred_at=datetime.now(UTC),
            note=note,
        )
    )

    def reset_storage_mode_override(
        reset_id: str,
    ) -> dict[str, object]:
        return _reset_storage_mode_override_and_request_replan(
            runtime=storage_mode_provenance_runtime,
            replan_requested=planning_reset_requested,
            reset_id=reset_id,
            reset_at=datetime.now(UTC),
        )

    web_view_store.set_storage_mode_override_reset(
        reset_storage_mode_override
    )

    def reset_planning(reset_id: str) -> dict[str, object]:
        if not reset_id.strip():
            raise ValueError("reset_id must be explicit")

        def clear_planning_state() -> tuple[ActivePlanCommitment, ...]:
            removed = active_plan_commitment_store.clear_all()
            active_plan_commitment_store.record_manual_reset(
                reset_id=reset_id,
                removed=removed,
            )
            canonical_execution_runtime.reset_pending_state()
            return removed

        reset_generation, removed = planning_reset_barrier.reset(
            clear_planning_state
        )
        planning_reset_requested.set()
        return {
            "status": "manual_planning_reset_requested",
            "reset_id": reset_id,
            "reset_generation": reset_generation,
            "removed_commitment_count": len(removed),
            "removed_plan_ids": [item.plan_id for item in removed],
            "history_preserved": True,
        }

    web_view_store.set_planning_reset(reset_planning)
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
    dashboard_power_history_specs = _dashboard_power_history_specs(options)

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
    latest_daily_observer_snapshot: PlanningInputSnapshot | None = None
    latest_daily_pv_basis_decision: DailyPVBasisDecision | None = None

    def prepare_bundle(
        bundle: PlanningInputBundle,
    ) -> tuple[
        PlanningInputBundle,
        LivePVActualDiagnostics,
    ]:
        nonlocal previous_household_regime
        nonlocal household_regime_started_at
        nonlocal latest_daily_observer_snapshot
        nonlocal latest_daily_pv_basis_decision
        bundle = attach_storage_mode_provenance(
            bundle,
            storage_mode_provenance_runtime,
        )
        bundle = replace(
            bundle,
            snapshot=_restore_active_plan_commitments(
                bundle.snapshot,
                active_plan_commitment_store,
            ),
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
        try:
            requirement_derivation = CandidateEngine().derive_storage_requirements(
                prepared_bundle.snapshot
            )
            storage_feasibility = derive_remaining_pv_storage_feasibility(
                prepared_bundle.snapshot,
                requirements=requirement_derivation.requirements,
                balances=requirement_derivation.balances,
            )
        except CandidateInputError:
            storage_feasibility = RemainingPVStorageFeasibility(
                status="unavailable",
                remaining_storage_need_wh=None,
                conservative_remaining_pv_surplus_wh=None,
                margin_wh=None,
                required_by=None,
                evidence_ids=(),
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
            storage_feasibility=storage_feasibility,
        )
        current_regime = prepared_bundle.snapshot.household_planning_regime
        if current_regime is not None and (
            previous_household_regime is None
            or current_regime.regime != previous_household_regime.regime
        ):
            household_regime_started_at = captured_at
        previous_household_regime = current_regime
        (
            latest_daily_observer_snapshot,
            latest_daily_pv_basis_decision,
        ) = apply_daily_measured_pv_basis(
            prepared_bundle.snapshot,
            diagnostics=diagnostics,
            local_timezone=pv_sunset_timezone,
        )
        return prepared_bundle, diagnostics

    def read_power_history(
        bundle: PlanningInputBundle,
    ) -> tuple[PowerHistorySnapshot, float]:
        captured_at = bundle.snapshot.captured_at
        history_starts_at = captured_at.astimezone(
            pv_sunset_timezone
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        power_history_started = perf_counter()
        power_history = power_history_cache.update(
            power_history_reader,
            specs=dashboard_power_history_specs,
            starts_at=history_starts_at - FINANCIAL_ANCHOR_LOOKBACK,
            ends_at=captured_at,
        )
        power_history = rebase_power_history(
            power_history,
            starts_at=history_starts_at,
        )
        power_history = _attach_household_power_history(
            power_history,
            household_load_history.load(),
        )
        power_history_read_ms = round(
            (perf_counter() - power_history_started) * 1000.0,
            3,
        )
        return power_history, power_history_read_ms

    previous_observer_signature: str | None = None

    def observe_fresh_input(bundle: PlanningInputBundle) -> None:
        nonlocal previous_observer_signature
        web_view_store.publish_planning_input_sources(
            _planning_input_sources(bundle)
        )
        signature = _observer_input_signature(bundle)
        if _should_run_cycle(previous_signature, bundle):
            # The canonical execution path submits this snapshot. Remember its
            # observer signature to avoid queueing it again on the next poll.
            previous_observer_signature = signature
            return
        if signature == previous_observer_signature:
            return
        previous_observer_signature = signature
        independent_daily_observer_worker.submit(
            latest_daily_observer_snapshot or bundle.snapshot
        )

    def refresh_unchanged(bundle: PlanningInputBundle) -> None:
        power_history, _ = read_power_history(bundle)
        try:
            planner_comparison_ledger.ingest(bundle.snapshot, power_history)
        except Exception as exc:
            report_daily_observer_error(bundle.snapshot, exc)
        web_view_store.publish_power_history(power_history)
        try:
            web_view_store.publish_financial_results(
                financial_result_ledger.update(
                    bundle.snapshot,
                    power_history,
                    price_points=tuple(
                        point
                        for evidence in bundle.evidence
                        for point in evidence.price_points
                    ),
                )
            )
        except Exception as exc:
            report_daily_observer_error(bundle.snapshot, exc)
        try:
            web_view_store.publish_planner_comparison_history(
                planner_comparison_ledger.dashboard_view()
            )
        except Exception as exc:
            report_daily_observer_error(bundle.snapshot, exc)

    def advance_market_daily_boundary(bundle: PlanningInputBundle) -> None:
        if (
            market_daily_refresh_at is not None
            and bundle.snapshot.captured_at >= market_daily_refresh_at
        ):
            market_daily_planner_worker.advance(bundle.snapshot)

    def execute(
        bundle: PlanningInputBundle,
        pv_actual_diagnostics: LivePVActualDiagnostics,
    ) -> None:
        power_history, power_history_read_ms = read_power_history(bundle)
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
            power_history=power_history,
            power_history_read_ms=power_history_read_ms,
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
            storage_mode_transition_history=(
                storage_mode_transition_history
            ),
            canonical_execution_runtime=canonical_execution_runtime,
            canonical_execution_enabled=canonical_execution_enabled,
            micro_charge_suppression_fraction=(
                micro_charge_suppression_fraction
            ),
            planning_fallback_notifier=planning_fallback_notifier,
            planning_incident_history=planning_incident_history,
            independent_daily_observer_worker=(
                independent_daily_observer_worker
            ),
            independent_daily_snapshot=latest_daily_observer_snapshot,
            daily_pv_basis_decision=latest_daily_pv_basis_decision,
            market_daily_planner_worker=market_daily_planner_worker,
            planner_comparison_ledger=planner_comparison_ledger,
            financial_result_ledger=financial_result_ledger,
        )

    previous_signature: str | None = None
    while True:
        if planning_reset_requested.is_set():
            planning_reset_requested.clear()
            previous_signature = None
        previous_signature = planning_reset_barrier.run_cycle(
            partial(
                _poll_live_cycle,
                previous_signature=previous_signature,
                load_bundle=load_bundle,
                prepare_bundle=prepare_bundle,
                execute=execute,
                persist_observation=household_load_history.append,
                refresh_unchanged=refresh_unchanged,
                advance_clock_boundaries=advance_market_daily_boundary,
                observe=observe_fresh_input,
            )
        )
        _wait_for_poll_or_reset(
            planning_reset_requested,
            poll_interval_seconds,
        )


if __name__ == "__main__":
    main()
