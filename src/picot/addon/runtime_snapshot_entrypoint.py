"""Runtime composition entrypoint that adds atomic snapshot evidence per poll."""

from __future__ import annotations

from picot.addon import runtime_observation
from picot.addon.live_snapshot_runtime import (
    build_live_planning_snapshot,
    snapshot_log_event,
)

_base_evidence_events = runtime_observation._telemetry_evidence_events
_snapshot_sequence = 0


def telemetry_evidence_events_with_snapshot(
    telemetry_event: dict[str, object],
) -> list[dict[str, object]]:
    """Append one observation-only PlanningInputSnapshot record to one poll."""

    global _snapshot_sequence
    events = _base_evidence_events(telemetry_event)
    _snapshot_sequence += 1
    snapshot = build_live_planning_snapshot(
        telemetry_event,
        sequence=_snapshot_sequence,
    )
    events.append(snapshot_log_event(snapshot))
    return events


def main() -> int:
    """Run the existing telemetry loop with snapshot evidence composed in."""

    runtime_observation._telemetry_evidence_events = telemetry_evidence_events_with_snapshot
    return runtime_observation.main()


if __name__ == "__main__":
    raise SystemExit(main())
