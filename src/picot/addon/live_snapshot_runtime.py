"""Build an atomic PlanningInputSnapshot from one normalized telemetry poll."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from picot.addon.household_load_forecaster import HouseholdLoadForecaster
from picot.addon.planning_snapshot_assembly import (
    NormalizedPlanningInputs,
    assemble_planning_input_snapshot,
)
from picot.domain.current_flow_observation import CurrentFlowObservation
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


def current_flow_observation_from_telemetry(
    event: dict[str, object], *, sequence: int, captured_at: datetime
) -> CurrentFlowObservation | None:
    grid_export_w = _number(event, "flow_observer_grid_export_w")
    discharge_w = _number(event, "flow_observer_battery_discharge_w")
    pv_power_w = _number(event, "flow_observer_pv_power_w")
    persistent = event.get("flow_observer_persistent_mismatch")
    discharge_while_exporting = event.get("flow_observer_discharge_while_exporting")
    consecutive = event.get("flow_observer_consecutive_samples", 0)
    required = event.get("flow_observer_required_samples", 0)
    if (
        grid_export_w is None
        or discharge_w is None
        or pv_power_w is None
        or not isinstance(persistent, bool)
        or not isinstance(discharge_while_exporting, bool)
        or isinstance(consecutive, bool)
        or not isinstance(consecutive, int)
        or isinstance(required, bool)
        or not isinstance(required, int)
    ):
        return None
    regime = event.get("flow_observer_control_regime")
    band = event.get("flow_observer_validation_band")
    return CurrentFlowObservation(
        observation_id=f"live-flow-{sequence}",
        observed_at=captured_at,
        grid_export_w=grid_export_w,
        battery_discharge_w=discharge_w,
        pv_power_w=pv_power_w,
        discharge_while_exporting=discharge_while_exporting,
        persistent_mismatch=persistent,
        consecutive_samples=consecutive,
        required_samples=required,
        evidence_ids=(f"flow-observer-sample-{sequence}",),
        control_regime=regime if isinstance(regime, str) else None,
        validation_band=band if isinstance(band, str) else None,
        tracking_deviation_w=_number(event, "flow_observer_tracking_deviation_w"),
        grey_elapsed_s=_number(event, "flow_observer_grey_elapsed_s") or 0.0,
        red_elapsed_s=_number(event, "flow_observer_red_elapsed_s") or 0.0,
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
    event: dict[str, object],
    *,
    sequence: int,
    horizon_hours: int = 24,
    load_forecaster: HouseholdLoadForecaster | None = None,
) -> PlanningInputSnapshot:
    if sequence < 1:
        raise ValueError("Snapshot sequence must be at least 1.")
    captured_at = _timestamp(event, "telemetry_updated_at")
    if captured_at is None:
        raise ValueError("Telemetry event requires telemetry_updated_at.")
    household_state = household_state_from_telemetry(event)
    storage_state = current_storage_state_from_telemetry(event, sequence=sequence)
    flow_observation = current_flow_observation_from_telemetry(
        event,
        sequence=sequence,
        captured_at=captured_at,
    )
    pv_timeline = pv_energy_timeline_from_telemetry(
        event,
        sequence=sequence,
        captured_at=captured_at,
    )
    household_load_forecast = None
    if load_forecaster is not None and pv_timeline is not None:
        load_forecaster.observe(
            measured_at=household_state.measured_at,
            household_load_w=household_state.household_load_w,
        )
        household_load_forecast = load_forecaster.forecast(
            captured_at=captured_at,
            pv_timeline=pv_timeline,
            current_household_load_w=household_state.household_load_w,
            sequence=sequence,
        )
    horizon_end = (
        pv_timeline.horizon_end
        if pv_timeline is not None
        else captured_at + timedelta(hours=horizon_hours)
    )
    snapshot = assemble_planning_input_snapshot(
        snapshot_id=f"live-observation-{captured_at.isoformat()}-{sequence}",
        captured_at=captured_at,
        horizon_end=horizon_end,
        strategy=_runtime_strategy(),
        inputs=NormalizedPlanningInputs(
            household_state=household_state,
            forecasts=ForecastSet(series=()),
            current_storage_states=((storage_state,) if storage_state is not None else ()),
            household_load_forecast=household_load_forecast,
            pv_energy_timeline=pv_timeline,
            current_flow_observation=flow_observation,
        ),
        versions=PlanningInputVersions(
            capability_mapping=1,
            user_rules=1,
            commitments=1,
            household_state=1,
            forecasts=1,
        ),
        replan_reasons=("live_observation",),
    )
    if pv_timeline is not None and pv_timeline.horizon_end != horizon_end:
        snapshot = replace(snapshot, horizon_end=pv_timeline.horizon_end)
    return snapshot


def snapshot_log_event(snapshot: PlanningInputSnapshot) -> dict[str, object]:
    """Return an explainable persisted event for the atomic planning snapshot."""

    return {
        "event": "planning_input_snapshot",
        "layer": "planning_input",
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "horizon_end": snapshot.horizon_end.isoformat(),
        "storage_state_count": len(snapshot.current_storage_states),
        "has_pv_energy_timeline": snapshot.pv_energy_timeline is not None,
        "has_household_load_forecast": snapshot.household_load_forecast is not None,
        "has_current_flow_observation": snapshot.current_flow_observation is not None,
        "replan_reasons": list(snapshot.replan_reasons),
    }
