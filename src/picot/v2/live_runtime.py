"""Minimal live runtime for PicoT v2.0.0-dev.1."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from time import perf_counter

from picot.v2.ha_projection_sink import HomeAssistantProjectionSink
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import Card, project


def main() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("Supervisor token is required")

    started = perf_counter()
    run = CanonicalPipeline().run()
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
                "planner_cycle_ms": planner_cycle_ms,
                "diagnostic_projection_ms": projection.projection_ms,
                "serialization_ms": serialization_ms,
                "ha_publish_ms": publish_ms,
                "persistence_ms": 0.0,
                "trace_events_per_run": len(projection.cards),
                "buffer_depth": 0,
                "observer_only": True,
            },
        )
    )

    print(
        json.dumps(
            {
                "event": "picot_v2_bootstrap_ready",
                "version": run.planning_input.picot_version,
                "run_id": run.planning_input.run_id,
                "snapshot_id": run.planning_input.snapshot_id,
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
