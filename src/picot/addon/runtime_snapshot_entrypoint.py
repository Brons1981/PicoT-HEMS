"""Runtime composition entrypoint that adds atomic snapshot evidence per poll."""

from __future__ import annotations

import json
from typing import Any, cast

from picot.addon import runtime, runtime_observation
from picot.addon.live_snapshot_runtime import (
    build_live_planning_snapshot,
    snapshot_log_event,
)

_base_evidence_events = runtime_observation._telemetry_evidence_events
_snapshot_sequence = 0
_storage_usable_capacity_wh: float | None = None


def telemetry_evidence_events_with_snapshot(
    telemetry_event: dict[str, object],
) -> list[dict[str, object]]:
    """Append one enriched PlanningInputSnapshot record to one telemetry poll."""

    global _snapshot_sequence
    events = _base_evidence_events(telemetry_event)
    _snapshot_sequence += 1
    snapshot_input = dict(telemetry_event)
    if _storage_usable_capacity_wh is not None:
        snapshot_input["storage_usable_capacity_wh"] = _storage_usable_capacity_wh
    snapshot = build_live_planning_snapshot(
        snapshot_input,
        sequence=_snapshot_sequence,
    )
    events.append(snapshot_log_event(snapshot))
    return events


def main() -> int:
    """Run the existing telemetry loop with snapshot evidence composed in."""

    global _storage_usable_capacity_wh
    with runtime.OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))
    _storage_usable_capacity_wh = float(options["storage_usable_capacity_wh"])
    runtime_observation._telemetry_evidence_events = telemetry_evidence_events_with_snapshot
    return runtime_observation.main()


if __name__ == "__main__":
    raise SystemExit(main())
