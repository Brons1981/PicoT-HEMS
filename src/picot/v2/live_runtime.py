"""Live runtime for the PicoT v2 canonical validation pipeline.

Performance diagnostics remain observational and outside planner decision logic.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from http.server import ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from threading import Thread
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.household_load_history import HouseholdLoadHistoryStore
from picot.v2.live_pv_actual import (
    LivePVActualCache,
    LivePVActualDiagnostics,
    apply_latest_closed_actual_pv,
)
from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
    attach_storage_mode_provenance,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline, PipelineStageTimings
from picot.v2.planning_input import (
    HouseholdLoadObservation,
    PlanningInputBundle,
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
) -> None:
    """Run, project, and publish one already assembled Planning Input bundle."""
    planning_input_ms = round(
        (bundle.assembly_finished_at - bundle.assembly_started_at).total_seconds() * 1000.0,
        3,
    )

    run, stage_timings = CanonicalPipeline().run_timed(
        planning_input=bundle.snapshot,
        price_opportunity_config=price_config,
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
    web_view_store = WebViewStore()
    household_load_history = HouseholdLoadHistoryStore(
        HOUSEHOLD_LOAD_HISTORY_PATH
    )
    pv_history_reader = HomeAssistantPVHistoryReader(token)
    pv_actual_cache = LivePVActualCache()
    storage_mode_provenance_runtime = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(STORAGE_MODE_PROVENANCE_PATH)
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

    def prepare_bundle(
        bundle: PlanningInputBundle,
    ) -> tuple[
        PlanningInputBundle,
        LivePVActualDiagnostics,
    ]:
        bundle = attach_storage_mode_provenance(
            bundle,
            storage_mode_provenance_runtime,
        )
        if bundle.snapshot.pv_energy_timeline is not None:
            pv_attenuation_learning.capture_forecast_basis(
                timeline=bundle.snapshot.pv_energy_timeline,
                captured_at=bundle.snapshot.captured_at,
            )
        return apply_latest_closed_actual_pv(
            bundle,
            entity_id=pv_power_entity,
            history_reader=pv_history_reader.read,
            cache=pv_actual_cache,
            telemetry_interval_seconds=(
                pv_telemetry_interval_seconds
            ),
        )

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
