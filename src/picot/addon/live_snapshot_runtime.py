"""Build an atomic PlanningInputSnapshot from one normalized telemetry poll."""

from __future__ import annotations

from datetime import datetime, timedelta

from picot.addon.planning_snapshot_assembly import (
    NormalizedPlanningInputs,
    assemble_planning_input_snapshot,
)
from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.forecast import ForecastSet
from picot.domain.household_state import HouseholdState
from picot.domain.objectives import OptimisationProfile, PlannerStrategy
from picot.domain.planning_input_snapshot import PlanningInputSnapshot, PlanningInputVersions
from picot.domain.pv_energy_timeline import (
    PVEnergyEvidenceType,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)


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
    measured_at = _timestamp(event, "telemetry_updated_at")
    if measured_at is None:
        raise ValueError("Telemetry event requires telemetry_updated_at.")
    grid_power = _number(event, "grid_power_w")
    pv_power = _number(event, "goodwe_solar_power_w")
    battery_power = _number(event, "zendure_signed_power_w")
    household_load = None
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


def current_storage_state_from_telemetry(
    event: dict[str, object], *, sequence: int
) -> CurrentStorageState | None:
    soc_percent = _number(event, "zendure_soc_percent")
    capacity_wh = _number(event, "storage_usable_capacity_wh")
    measured_at = _timestamp(event, "zendure_observed_at")
    if soc_percent is None or capacity_wh is None or measured_at is None:
        return None
    if not 0.0 <= soc_percent <= 100.0 or capacity_wh <= 0:
        return None
    return CurrentStorageState(
        storage_state_id=f"live-storage-{sequence}",
        execution_scope_id="storage-primary",
        capability_id="storage-primary-energy",
        current_soc=soc_percent / 100.0,
        usable_capacity_wh=capacity_wh,
        measured_at=measured_at,
        confidence=1.0,
        evidence_ids=(f"zendure-observation-{sequence}",),
    )


def _forecast_points(
    event: dict[str, object], key: str, confidence_key: str
) -> list[tuple[datetime, float, float]]:
    raw_points = event.get(key, [])
    confidence = _number(event, confidence_key)
    if not isinstance(raw_points, list) or confidence is None:
        return []
    parsed: list[tuple[datetime, float, float]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        start = item.get("period_start")
        estimate = item.get("pv_estimate")
        if (
            not isinstance(start, str)
            or isinstance(estimate, bool)
            or not isinstance(estimate, (int, float))
        ):
            continue
        moment = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            continue
        parsed.append((moment, max(0.0, float(estimate)), confidence))
    return parsed


def pv_energy_timeline_from_telemetry(
    event: dict[str, object], *, sequence: int, captured_at: datetime
) -> PVEnergyTimeline | None:
    parsed = _forecast_points(
        event,
        "solcast_today_forecast_points",
        "solcast_today_confidence",
    )
    parsed.extend(
        _forecast_points(
            event,
            "solcast_tomorrow_forecast_points",
            "solcast_tomorrow_confidence",
        )
    )
    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        return None

    intervals: list[PVEnergyTimelineInterval] = []
    for (start, estimate_kw, confidence), (next_start, _, _) in zip(
        parsed, parsed[1:], strict=False
    ):
        if next_start <= captured_at:
            continue
        effective_start = max(start, captured_at)
        if effective_start >= next_start:
            continue
        hours = (next_start - effective_start).total_seconds() / 3600.0
        intervals.append(
            PVEnergyTimelineInterval(
                starts_at=effective_start,
                ends_at=next_start,
                energy_wh=estimate_kw * 1000.0 * hours,
                evidence_type=PVEnergyEvidenceType.FORECAST,
                confidence=confidence,
                evidence_ids=(f"solcast-forecast-{sequence}",),
                method_version="solcast-power-to-energy-v1",
            )
        )
    if not intervals or intervals[0].starts_at != captured_at:
        return None
    return PVEnergyTimeline(
        timeline_id=f"live-pv-{sequence}",
        created_at=captured_at,
        horizon_start=captured_at,
        horizon_end=intervals[-1].ends_at,
        intervals=tuple(intervals),
    )


def _runtime_strategy() -> PlannerStrategy:
    return PlannerStrategy(
        strategy_version=1,
        source_profile_version=1,
        mapping_version="live-observation-v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(),
    )


def build_live_planning_snapshot(
    event: dict[str, object], *, sequence: int, horizon_hours: int = 24
) -> PlanningInputSnapshot:
    if sequence < 1:
        raise ValueError("Snapshot sequence must be at least 1.")
    captured_at = _timestamp(event, "telemetry_updated_at")
    if captured_at is None:
        raise ValueError("Telemetry event requires telemetry_updated_at.")
    storage_state = current_storage_state_from_telemetry(event, sequence=sequence)
    pv_timeline = pv_energy_timeline_from_telemetry(
        event,
        sequence=sequence,
        captured_at=captured_at,
    )
    horizon_end = (
        pv_timeline.horizon_end
        if pv_timeline is not None
        else captured_at + timedelta(hours=horizon_hours)
    )
    return assemble_planning_input_snapshot(
        snapshot_id=f"live-observation-{captured_at.isoformat()}-{sequence}",
        captured_at=captured_at,
        horizon_end=horizon_end,
        strategy=_runtime_strategy(),
        inputs=NormalizedPlanningInputs(
            household_state=household_state_from_telemetry(event),
            forecasts=ForecastSet(series=()),
            current_storage_states=((storage_state,) if storage_state is not None else ()),
            pv_energy_timeline=pv_timeline,
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
    state = snapshot.household_state
    storage = snapshot.current_storage_states[0] if snapshot.current_storage_states else None
    pv_timeline = snapshot.pv_energy_timeline
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
        "current_soc": storage.current_soc if storage is not None else None,
        "usable_capacity_wh": storage.usable_capacity_wh if storage is not None else None,
        "pv_timeline_energy_wh": (
            pv_timeline.total_energy_wh if pv_timeline is not None else None
        ),
        "household_state_version": snapshot.versions.household_state,
        "status": "observation_plus_storage_pv",
    }
