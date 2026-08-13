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
from picot.v2.projection import Card, project


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

    projection = project(run)
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
