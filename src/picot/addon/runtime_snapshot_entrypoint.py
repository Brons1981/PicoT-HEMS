"""Runtime composition entrypoint that adds atomic snapshot evidence per poll."""

from __future__ import annotations

import json
from typing import Any, cast

from picot.addon import runtime, runtime_observation
from picot.addon.adr037_dashboard import publish_adr037_dashboard_states
from picot.addon.household_load_forecaster import HouseholdLoadForecaster
from picot.addon.live_adr037_readiness import adr037_readiness_log_event
from picot.addon.live_planner_context import LiveEvidenceConfidenceTracker
from picot.addon.live_snapshot_runtime import (
    build_live_planning_snapshot,
    snapshot_log_event,
)
from picot.addon.live_storage_constraints import (
    build_effective_storage_limit,
    build_live_storage_capabilities,
)

_base_evidence_events = runtime_observation._telemetry_evidence_events
_base_publish_telemetry_states = runtime_observation._publish_telemetry_states
_snapshot_sequence = 0
_storage_usable_capacity_wh: float | None = None
_storage_max_soc = 1.0
_storage_max_charge_power_w: float | None = None
_storage_power_step_w: float | None = None
_load_forecaster = HouseholdLoadForecaster()
_confidence_tracker = LiveEvidenceConfidenceTracker()


def _soc_fraction(event: dict[str, object], key: str) -> float | None:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    percentage = float(value)
    if not 0.0 <= percentage <= 100.0:
        return None
    return percentage / 100.0


def telemetry_evidence_events_with_snapshot(
    telemetry_event: dict[str, object],
) -> list[dict[str, object]]:
    """Append one enriched PlanningInputSnapshot and live planner evidence per poll."""

    global _snapshot_sequence
    events = _base_evidence_events(telemetry_event)
    _snapshot_sequence += 1
    snapshot_input = dict(telemetry_event)
    if _storage_usable_capacity_wh is not None:
        snapshot_input["storage_usable_capacity_wh"] = _storage_usable_capacity_wh
    snapshot = build_live_planning_snapshot(
        snapshot_input,
        sequence=_snapshot_sequence,
        load_forecaster=_load_forecaster,
    )
    events.append(snapshot_log_event(snapshot))

    live_max_soc = _soc_fraction(telemetry_event, "zendure_allowed_max_soc_percent")
    effective_max_soc = live_max_soc if live_max_soc is not None else _storage_max_soc
    capabilities = build_live_storage_capabilities(
        captured_at=snapshot.captured_at,
        snapshot_id=snapshot.snapshot_id,
        maximum_charge_power_w=_storage_max_charge_power_w,
        power_step_w=_storage_power_step_w,
        maximum_soc=effective_max_soc,
    )
    effective_limit = None
    if snapshot.current_storage_states:
        effective_limit = build_effective_storage_limit(
            storage_state=snapshot.current_storage_states[0],
            maximum_soc=effective_max_soc,
            sequence=_snapshot_sequence,
        )
    readiness = adr037_readiness_log_event(
        snapshot,
        capabilities=capabilities,
        effective_limit=effective_limit,
        confidence_tracker=_confidence_tracker,
        planner_context=telemetry_event,
    )
    events.append(readiness)
    telemetry_event.update(readiness)
    return events


def publish_telemetry_states_with_adr037(
    event: dict[str, object], token: str
) -> None:
    """Publish existing telemetry states plus the ADR-037 observer sensor."""

    _base_publish_telemetry_states(event, token)
    publish_adr037_dashboard_states(event, token)


def main() -> int:
    """Run the existing telemetry loop with snapshot evidence composed in."""

    global _storage_max_charge_power_w
    global _storage_max_soc
    global _storage_power_step_w
    global _storage_usable_capacity_wh

    with runtime.OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))
    _storage_usable_capacity_wh = float(options["storage_usable_capacity_wh"])
    _storage_max_soc = float(options.get("storage_max_soc_percent", 100)) / 100.0
    configured_max_power = float(options.get("storage_max_charge_power_w", 0))
    _storage_max_charge_power_w = configured_max_power if configured_max_power > 0 else None
    configured_step = float(options.get("storage_power_step_w", 0))
    _storage_power_step_w = configured_step if configured_step > 0 else None
    runtime_observation._telemetry_evidence_events = telemetry_evidence_events_with_snapshot
    runtime_observation._publish_telemetry_states = publish_telemetry_states_with_adr037
    return runtime_observation.main()


if __name__ == "__main__":
    raise SystemExit(main())
