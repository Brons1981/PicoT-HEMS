"""Runtime composition entrypoint that adds atomic snapshot evidence per poll."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from time import perf_counter
from typing import Any, cast

from picot.addon import price_runtime_v2, runtime, runtime_observation
from picot.addon.actual_pv_energy import prepend_actual_pv_evidence
from picot.addon.adr037_dashboard import publish_adr037_dashboard_states
from picot.addon.canonical_pv_deviation import (
    CanonicalPVDeviationEvaluator,
    quarter_anchor_event,
    runtime_monitor_fields,
)
from picot.addon.execution_engine_dashboard import publish_execution_engine_state
from picot.addon.household_load_forecaster import HouseholdLoadForecaster
from picot.addon.live_adr037_readiness import run_adr037_readiness
from picot.addon.live_execution_engine_observer import observe_execution_engine
from picot.addon.live_execution_plan_observer import observe_execution_plan_set
from picot.addon.live_flow_observer import LiveFlowObserver
from picot.addon.live_mode_control import LiveModeControl
from picot.addon.live_planner_context import LiveEvidenceConfidenceTracker
from picot.addon.live_snapshot_runtime import (
    build_live_planning_snapshot,
    snapshot_log_event,
)
from picot.addon.live_storage_constraints import (
    build_effective_storage_limit,
    build_live_storage_capabilities,
)
from picot.addon.runtime_performance_dashboard import publish_runtime_performance_state
from picot.domain.forecast import ForecastSeries, ForecastSet
from picot.domain.home_assistant import HomeAssistantDispatchMode

_base_evidence_events = runtime_observation._telemetry_evidence_events
_base_publish_telemetry_states = runtime_observation._publish_telemetry_states
_snapshot_sequence = 0
_storage_usable_capacity_wh: float | None = None
_storage_max_soc = 1.0
_storage_max_charge_power_w: float | None = None
_storage_power_step_w: float | None = None
_target_entity: str | None = None
_price_entity: str | None = None
_price_opportunity_margin_eur_per_kwh = 0.04
_dispatch_mode = HomeAssistantDispatchMode.DRY_RUN
_supervisor_token = ""
_load_forecaster = HouseholdLoadForecaster()
_confidence_tracker = LiveEvidenceConfidenceTracker()
_flow_observer = LiveFlowObserver()
_mode_control = LiveModeControl()
_canonical_pv_deviation = CanonicalPVDeviationEvaluator(history=_load_forecaster.history)


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000.0, 3)


def _soc_fraction(event: dict[str, object], key: str) -> float | None:
    value = event.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    percentage = float(value)
    if not 0.0 <= percentage <= 100.0:
        return None
    return percentage / 100.0


def _live_price_forecast(*, captured_at: Any) -> ForecastSeries | None:
    """Read the authoritative HA price forecast for this live Planner Run."""

    if _price_entity is None or not _supervisor_token:
        return None
    try:
        raw_state = runtime._request_json(f"/api/states/{_price_entity}", _supervisor_token)
        return runtime._price_forecast(raw_state, now=cast(Any, captured_at))
    except Exception:
        return None


def _apply_mode_control(
    telemetry_event: dict[str, object], *, captured_at: object
) -> dict[str, object]:
    if _target_entity is None or not _supervisor_token:
        return {
            "event": "picot_live_mode_control",
            "layer": "execution",
            "adr037_control_status": "execution_context_unavailable",
            "adr037_control_dispatch_status": "not_attempted",
            "control_change_allowed": False,
            "observer_only": True,
        }
    if not hasattr(captured_at, "tzinfo"):
        return {
            "event": "picot_live_mode_control",
            "layer": "execution",
            "adr037_control_status": "invalid_snapshot_time",
            "adr037_control_dispatch_status": "not_attempted",
            "control_change_allowed": False,
            "observer_only": True,
        }
    try:
        fields = _mode_control.apply(
            telemetry_event,
            target_entity=_target_entity,
            mode=_dispatch_mode,
            token=_supervisor_token,
            now=cast(Any, captured_at),
            dispatch=runtime._dispatch,
        )
    except Exception as exc:
        fields = {
            "adr037_control_status": "dispatch_failed_closed",
            "adr037_control_requested_option": None,
            "adr037_control_dispatch_status": "failed",
            "adr037_control_error": str(exc) or exc.__class__.__name__,
            "control_change_allowed": False,
            "observer_only": _dispatch_mode is HomeAssistantDispatchMode.DRY_RUN,
        }
    return {
        "event": "picot_live_mode_control",
        "layer": "execution",
        "snapshot_id": telemetry_event.get("snapshot_id"),
        "captured_at": telemetry_event.get("captured_at"),
        **fields,
    }


def _captured_at(event: dict[str, object]) -> datetime:
    raw = event.get("telemetry_updated_at")
    if not isinstance(raw, str):
        raise ValueError("Telemetry event requires telemetry_updated_at.")
    captured = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("Telemetry timestamp must be timezone-aware.")
    return captured


def telemetry_evidence_events_with_snapshot(
    telemetry_event: dict[str, object],
) -> list[dict[str, object]]:
    """Append canonical runtime evidence and one fresh PlanningInputSnapshot per poll."""

    cycle_started = perf_counter()
    timings: dict[str, float] = {}
    global _snapshot_sequence

    stage_started = perf_counter()
    events = _base_evidence_events(telemetry_event)
    timings["base_evidence_ms"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    flow_fields = _flow_observer.evaluate(telemetry_event)
    timings["flow_observer_ms"] = _elapsed_ms(stage_started)
    telemetry_event.update(flow_fields)
    events.append(
        {
            "event": "picot_live_flow_observation",
            "layer": "closed_loop_observer",
            "observed_at": telemetry_event.get("telemetry_updated_at"),
            **flow_fields,
            "zendure_available_energy": telemetry_event.get("zendure_available_energy"),
            "zendure_required_energy": telemetry_event.get("zendure_required_energy"),
            "zendure_remaining_discharge_time": telemetry_event.get(
                "zendure_remaining_discharge_time"
            ),
            "zendure_remaining_charge_time": telemetry_event.get(
                "zendure_remaining_charge_time"
            ),
            "zendure_configured_discharge_power_w": telemetry_event.get(
                "zendure_configured_discharge_power_w"
            ),
            "zendure_configured_charge_power_w": telemetry_event.get(
                "zendure_configured_charge_power_w"
            ),
        }
    )

    captured_at = _captured_at(telemetry_event)
    cadence = telemetry_event.get("telemetry_interval_seconds", 5)
    cadence_seconds = (
        int(cadence)
        if isinstance(cadence, int) and not isinstance(cadence, bool)
        else 5
    )
    stage_started = perf_counter()
    deviation = _canonical_pv_deviation.evaluate(
        captured_at=captured_at,
        telemetry_interval_seconds=cadence_seconds,
    )
    timings["canonical_pv_deviation_ms"] = _elapsed_ms(stage_started)
    canonical_replan_required = False
    if deviation is not None:
        deviation_fields = deviation.as_fields()
        monitor_fields = runtime_monitor_fields(deviation, observed_at=captured_at)
        telemetry_event.update(deviation_fields)
        telemetry_event.update(monitor_fields)
        canonical_replan_required = bool(
            monitor_fields.get("canonical_pv_fresh_snapshot_required")
        )
        events.append(
            {
                "event": "picot_canonical_pv_deviation",
                "layer": "pv_forecast_validation",
                "observed_at": captured_at.isoformat(),
                **deviation_fields,
                **monitor_fields,
            }
        )

    _snapshot_sequence += 1
    snapshot_input = dict(telemetry_event)
    if _storage_usable_capacity_wh is not None:
        snapshot_input["storage_usable_capacity_wh"] = _storage_usable_capacity_wh
    stage_started = perf_counter()
    snapshot = build_live_planning_snapshot(
        snapshot_input,
        sequence=_snapshot_sequence,
        load_forecaster=_load_forecaster,
    )
    timings["snapshot_build_ms"] = _elapsed_ms(stage_started)
    if canonical_replan_required:
        snapshot = replace(
            snapshot,
            replan_reasons=tuple(
                dict.fromkeys((*snapshot.replan_reasons, "canonical_pv_deviation"))
            ),
        )

    stage_started = perf_counter()
    if snapshot.pv_energy_timeline is not None:
        anchor = quarter_anchor_event(
            timeline=snapshot.pv_energy_timeline,
            captured_at=snapshot.captured_at,
        )
        if anchor is not None:
            events.append(anchor)
        canonical_pv = prepend_actual_pv_evidence(
            timeline=snapshot.pv_energy_timeline,
            history=_load_forecaster.history,
            event=snapshot_input,
            captured_at=snapshot.captured_at,
            sequence=_snapshot_sequence,
        )
        snapshot = replace(snapshot, pv_energy_timeline=canonical_pv)
    timings["actual_pv_integration_ms"] = _elapsed_ms(stage_started)

    stage_started = perf_counter()
    price_forecast = _live_price_forecast(captured_at=snapshot.captured_at)
    timings["price_fetch_ms"] = _elapsed_ms(stage_started)
    if price_forecast is not None:
        snapshot = replace(snapshot, forecasts=ForecastSet(series=(price_forecast,)))
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

    stage_started = perf_counter()
    readiness_run = run_adr037_readiness(
        snapshot,
        capabilities=capabilities,
        effective_limit=effective_limit,
        confidence_tracker=_confidence_tracker,
        planner_context=telemetry_event,
        price_margin_eur_per_kwh=_price_opportunity_margin_eur_per_kwh,
    )
    timings["adr037_planner_ms"] = _elapsed_ms(stage_started)
    readiness = readiness_run.event
    readiness["adr037_typed_planning_result_available"] = (
        readiness_run.planning_result is not None
    )

    stage_started = perf_counter()
    plan_set, plan_fields = observe_execution_plan_set(
        readiness_run.planning_result,
        created_at=snapshot.captured_at,
    )
    timings["execution_plan_build_ms"] = _elapsed_ms(stage_started)
    readiness.update(plan_fields)
    events.append(
        {
            "event": "picot_execution_plan_set_observation",
            "layer": "plan_construction",
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at.isoformat(),
            "observer_only": True,
            **plan_fields,
        }
    )

    # ADR-047 authority is intentionally unverified in step 3. Persisted
    # provenance/reset semantics are a separate responsibility and are not
    # guessed from selector strings. Any raw primitive produced by the engine is
    # therefore suppressed fail-closed at composition until authority is proven.
    stage_started = perf_counter()
    execution_fields = observe_execution_engine(
        plan_set,
        capabilities,
        now=snapshot.captured_at,
        control_authority="unverified",
    )
    timings["execution_engine_ms"] = _elapsed_ms(stage_started)
    readiness.update(execution_fields)
    events.append(
        {
            "event": "picot_execution_engine_observation",
            "layer": "execution",
            "snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at.isoformat(),
            "execution_plan_set_id": plan_fields.get("execution_plan_set_id"),
            "observer_only": True,
            **execution_fields,
        }
    )

    events.append(readiness)
    telemetry_event.update(readiness)

    # TAB-001 remains the temporary execution bridge. Step 3 observes the
    # canonical ExecutionEngine output only; no Device Adapter or dispatch is
    # connected to emitted ExecutionPrimitiveRequest objects.
    stage_started = perf_counter()
    control_event = _apply_mode_control(telemetry_event, captured_at=snapshot.captured_at)
    timings["tab001_mode_control_ms"] = _elapsed_ms(stage_started)
    events.append(control_event)
    telemetry_event.update(control_event)

    timings["total_composed_cycle_ms"] = _elapsed_ms(cycle_started)
    performance_fields = {
        f"runtime_perf_{name}": value for name, value in timings.items()
    }
    telemetry_event.update(performance_fields)
    events.append(
        {
            "event": "picot_runtime_performance",
            "layer": "runtime_observation",
            "observed_at": captured_at.isoformat(),
            "observer_only": True,
            **performance_fields,
        }
    )
    return events


def publish_telemetry_states_with_adr037(
    event: dict[str, object], token: str
) -> None:
    """Publish base, planning, execution and performance independently."""

    failures: list[str] = []
    try:
        _base_publish_telemetry_states(event, token)
    except Exception as exc:
        failures.append(str(exc) or exc.__class__.__name__)
    try:
        publish_adr037_dashboard_states(event, token)
    except Exception as exc:
        failures.append(f"adr037: {str(exc) or exc.__class__.__name__}")
    try:
        publish_execution_engine_state(event, token)
    except Exception as exc:
        failures.append(f"execution: {str(exc) or exc.__class__.__name__}")
    try:
        publish_runtime_performance_state(event, token)
    except Exception as exc:
        failures.append(f"performance: {str(exc) or exc.__class__.__name__}")
    if failures:
        raise RuntimeError("Presentation publisher failure(s): " + " | ".join(failures))


def main() -> int:
    """Run the canonical live telemetry/planner loop with snapshot evidence composed in."""

    global _dispatch_mode
    global _price_entity
    global _price_opportunity_margin_eur_per_kwh
    global _storage_max_charge_power_w
    global _storage_max_soc
    global _storage_power_step_w
    global _storage_usable_capacity_wh
    global _supervisor_token
    global _target_entity

    with runtime.OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))
    _storage_usable_capacity_wh = float(options["storage_usable_capacity_wh"])
    _storage_max_soc = float(options.get("storage_max_soc_percent", 100)) / 100.0
    configured_max_power = float(options.get("storage_max_charge_power_w", 0))
    _storage_max_charge_power_w = configured_max_power if configured_max_power > 0 else None
    configured_step = float(options.get("storage_power_step_w", 0))
    _storage_power_step_w = configured_step if configured_step > 0 else None
    _target_entity = str(options["target_entity"])
    _price_entity = str(options["price_entity"])
    _price_opportunity_margin_eur_per_kwh = float(
        options["price_opportunity_margin_eur_per_kwh"]
    )
    _dispatch_mode = HomeAssistantDispatchMode(str(options["mode"]))
    _supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "")

    runtime_observation._run_price_planner_once = price_runtime_v2.run_planner_once
    runtime_observation._telemetry_evidence_events = telemetry_evidence_events_with_snapshot
    runtime_observation._publish_telemetry_states = publish_telemetry_states_with_adr037
    return runtime_observation.main()


if __name__ == "__main__":
    raise SystemExit(main())
