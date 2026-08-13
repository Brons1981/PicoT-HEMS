"""Minimal live runtime for PicoT v2.0.0-dev.2."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from time import perf_counter

from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_input import assemble_planning_input
from picot.v2.projection import Card, Projection, project


def _with_planning_input_diagnostics(projection: Projection, bundle: object) -> Projection:
    """Passively enrich card 1 from the already assembled Planning Input bundle."""
    evidence = getattr(bundle, "evidence")
    facts = getattr(bundle, "facts")
    sources = [
        {
            "category": item.category,
            "semantic_role": item.semantic_role,
            "entity_id": item.entity_id,
            "availability": item.availability,
            "raw_state": item.raw_state,
            "raw_unit": item.raw_unit,
            "canonical_value": fact.value,
            "canonical_unit": fact.unit,
            "fact_id": fact.fact_id,
            "evidence_id": item.evidence_id,
            "mapping_version": item.mapping_version,
            "observed_at": item.observed_at.isoformat() if item.observed_at else None,
            "confidence_status": fact.confidence_status,
        }
        for item, fact in zip(evidence, facts, strict=True)
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
            "sources": sources,
        },
    )
    return Projection(cards=(enriched, *projection.cards[1:]), projection_ms=projection.projection_ms)


def main() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("Supervisor token is required")

    planning_input_started = perf_counter()
    bundle = assemble_planning_input(token)
    planning_input_ms = round((perf_counter() - planning_input_started) * 1000.0, 3)

    started = perf_counter()
    run = CanonicalPipeline().run(planning_input=bundle.snapshot)
    planner_cycle_ms = round((perf_counter() - started) * 1000.0, 3)

    projection = _with_planning_input_diagnostics(project(run), bundle)
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
                "planning_input_ms": planning_input_ms,
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
                "cards": len(projection.cards),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
