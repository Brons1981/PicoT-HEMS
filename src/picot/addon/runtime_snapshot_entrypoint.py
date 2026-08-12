"""Runtime composition entrypoint that adds atomic snapshot evidence per poll."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any, cast

from picot.addon import price_runtime_v2, runtime, runtime_observation
from picot.addon.adr037_dashboard import publish_adr037_dashboard_states
from picot.addon.household_load_forecaster import HouseholdLoadForecaster
from picot.addon.live_adr037_readiness import adr037_readiness_log_event
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
        # Missing price evidence is represented by an empty ForecastSet and causes
        # dependent ADR-044 candidate generation to fail closed. No fallback path.
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


def telemetry_evidence_events_with_snapshot(
    telemetry_event: dict[str, object],
) -> list[dict[str, object]]:
    """Append one enriched PlanningInputSnapshot and live planner evidence per poll."""

    global _snapshot_sequence
    events = _base_evidence_events(telemetry_event)
    flow_fields = _flow_observer.evaluate(telemetry_event)
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

    _snapshot_sequence += 1
    snapshot_input = dict(telemetry_event)
    if _storage_usable_capacity_wh is not None:
        snapshot_input["storage_usable_capacity_wh"] = _storage_usable_capacity_wh
    snapshot = build_live_planning_snapshot(
        snapshot_input,
        sequence=_snapshot_sequence,
        load_forecaster=_load_forecaster,
    )
    price_forecast = _live_price_forecast(captured_at=snapshot.captured_at)
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
    readiness = adr037_readiness_log_event(
        snapshot,
        capabilities=capabilities,
        effective_limit=effective_limit,
        confidence_tracker=_confidence_tracker,
        planner_context=telemetry_event,
        price_margin_eur_per_kwh=_price_opportunity_margin_eur_per_kwh,
    )
    events.append(readiness)
    telemetry_event.update(readiness)

    control_event = _apply_mode_control(telemetry_event, captured_at=snapshot.captured_at)
    events.append(control_event)
    telemetry_event.update(control_event)
    return events


def publish_telemetry_states_with_adr037(
    event: dict[str, object], token: str
) -> None:
    """Publish base presentation and ADR-037 independently."""

    failures: list[str] = []
    try:
        _base_publish_telemetry_states(event, token)
    except Exception as exc:
        failures.append(str(exc) or exc.__class__.__name__)
    try:
        publish_adr037_dashboard_states(event, token)
    except Exception as exc:
        failures.append(f"adr037: {str(exc) or exc.__class__.__name__}")
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

    # The old Price Driven v1 runtime selected Zendure modes from a fixed
    # contiguous window. It is intentionally unreachable from the live add-on.
    # Price runtime v2 produces canonical price opportunities/evidence only.
    runtime_observation._run_price_planner_once = price_runtime_v2.run_planner_once
    runtime_observation._telemetry_evidence_events = telemetry_evidence_events_with_snapshot
    runtime_observation._publish_telemetry_states = publish_telemetry_states_with_adr037
    return runtime_observation.main()


if __name__ == "__main__":
    raise SystemExit(main())