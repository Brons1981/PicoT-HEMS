"""Build an atomic PlanningInputSnapshot from one normalized telemetry poll.

This module is the runtime bridge between the existing direct-source telemetry
collection and the ADR-040/ADR-017 snapshot boundary. It never reads Home
Assistant entities itself and never consumes sensor.picot_* mirror entities.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from picot.addon.planning_snapshot_assembly import (
    NormalizedPlanningInputs,
    assemble_planning_input_snapshot,
)
from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import PlanningInputSnapshot, PlanningInputVersions


def _number(event: dict[str, object], key: str) -> float | None:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _timestamp(event: dict[str, object], key: str) -> datetime | None:
    value = event.get(key)
    if not isinstance(value, str) or not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{key} must be timezone-aware.")
    return moment


def household_state_from_telemetry(event: dict[str, object]) -> HouseholdState:
    """Create one vendor-independent household observation from one poll.

    Values are reused from the already normalized direct-source poll. No source
    is re-read here. Missing source dimensions remain explicitly unknown.
    """

    measured_at = _timestamp(event, "telemetry_updated_at")
    if measured_at is None:
        raise ValueError("Telemetry event requires telemetry_updated_at.")

    grid_power = _number(event, "grid_power_w")
    pv_power = _number(event, "goodwe_solar_power_w")
    battery_power = _number(event, "zendure_signed_power_w")

    household_load: float | None = None
    if grid_power is not None and pv_power is not None and battery_power is not None:
        household_load = pv_power + grid_power - battery_power

    return HouseholdState(
        measured_at=measured_at,
        phases=(),
        grid_power_w=grid_power,
        pv_power_w=pv_power,
        battery_power_w=battery_power,
        household_load_w=household_load,
    )


def _runtime_strategy() -> PlannerStrategy:
    """Return an explicit strategy placeholder for observation-only snapshots."""

    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="live-observation-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def build_live_planning_snapshot(
    event: dict[str, object],
    *,
    sequence: int,
    horizon_hours: int = 24,
) -> PlanningInputSnapshot:
    """Freeze one telemetry poll into an observation-only atomic snapshot."""

    if sequence < 1:
        raise ValueError("Snapshot sequence must be at least 1.")
    if horizon_hours < 1:
        raise ValueError("Snapshot horizon must be at least one hour.")

    captured_at = _timestamp(event, "telemetry_updated_at")
    if captured_at is None:
        raise ValueError("Telemetry event requires telemetry_updated_at.")

    return assemble_planning_input_snapshot(
        snapshot_id=f"live-observation-{captured_at.isoformat()}-{sequence}",
        captured_at=captured_at,
        horizon_end=captured_at + timedelta(hours=horizon_hours),
        strategy=_runtime_strategy(),
        inputs=NormalizedPlanningInputs(
            household_state=household_state_from_telemetry(event),
            forecasts=ForecastSet(series=()),
        ),
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=sequence,
            forecasts=1,
        ),
        replan_reasons=("live_observation",),
    )


def snapshot_log_event(snapshot: PlanningInputSnapshot) -> dict[str, object]:
    """Return trace evidence without exposing Home Assistant entity IDs."""

    state = snapshot.household_state
    return {
        "event": "picot_live_planning_snapshot",
        "layer": "planning_input",
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "horizon_end": snapshot.horizon_end.isoformat(),
        "grid_power_w": state.grid_power_w,
        "pv_power_w": state.pv_power_w,
        "battery_power_w": state.battery_power_w,
        "household_load_w": state.household_load_w,
        "household_state_version": snapshot.versions.household_state,
        "status": "observation_only",
    }
