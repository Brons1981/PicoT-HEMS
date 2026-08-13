"""Live runtime for the PicoT v2 canonical validation pipeline.

Performance diagnostics remain observational and outside planner decision logic.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from hashlib import sha256
from time import perf_counter
from typing import Any

from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline, PipelineStageTimings
from picot.v2.planning_input import PlanningInputBundle, assemble_planning_input, load_options
from picot.v2.projection import Card, Projection, project


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
    payload = {
        "strategy_id": bundle.snapshot.strategy_id,
        "horizon_end": (
            bundle.snapshot.horizon_end.isoformat() if bundle.snapshot.horizon_end else None
        ),
        "facts": facts,
        "price_points": price_points,
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
) -> str:
    """Load fresh Planning Input and execute only when decision input changed."""
    bundle = load_bundle()
    return _run_live_cycle(
        previous_signature=previous_signature,
        bundle=bundle,
        execute=execute,
    )


def _with_planning_input_diagnostics(
    projection: Projection,
    bundle: PlanningInputBundle,
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
        },
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


def _execute_planning_bundle(
    *,
    token: str,
    price_config: PriceOpportunityConfig,
    bundle: PlanningInputBundle,
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

    projection = _with_planning_input_diagnostics(project(run), bundle)
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
    bundle = assemble_planning_input(token)
    _execute_planning_bundle(
        token=token,
        price_config=price_config,
        bundle=bundle,
    )

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
