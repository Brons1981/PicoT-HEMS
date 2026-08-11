"""Publish read-only PicoT planner diagnostics for Home Assistant.

The diagnostics view is deliberately observation-only. It exposes current and
rolling PV deviation, experimental 15/30/60-minute PV energy comparisons,
replan state and Plan Review evidence as semantic Home Assistant entities so HA
history can render them on a shared timeline.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0
ENERGY_WINDOWS_MINUTES = (15, 30, 60)

DashboardPayload = dict[str, object]
DashboardStates = dict[str, DashboardPayload]


def _measurement_attributes(
    friendly_name: str,
    icon: str,
    unit: str,
    event: dict[str, object],
) -> dict[str, object]:
    return {
        "friendly_name": friendly_name,
        "icon": icon,
        "state_class": "measurement",
        "unit_of_measurement": unit,
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }


def _energy_window_state(
    event: dict[str, object], minutes: int
) -> DashboardPayload:
    prefix = f"pv_energy_{minutes}m"
    attributes = _measurement_attributes(
        f"PicoT PV energie afwijking {minutes} min",
        "mdi:solar-power-variant-outline",
        "%",
        event,
    )
    attributes.update(
        {
            "observation_only": True,
            "window_minutes": minutes,
            "status": event.get(f"{prefix}_status", "unknown"),
            "solcast_expected_kwh": event.get(f"{prefix}_expected_kwh"),
            "goodwe_actual_kwh": event.get(f"{prefix}_actual_kwh"),
            "coverage_seconds": event.get(f"{prefix}_coverage_seconds"),
            "replan_input": False,
        }
    )
    return {
        "state": event.get(f"{prefix}_deviation_percent", "unknown"),
        "attributes": attributes,
    }


def diagnostics_dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build semantic states for the Developer/Diagnostics View."""

    replan_candidate = event.get("pv_deviation_replan_candidate") is True
    evaluator_status = event.get("pv_deviation_evaluator_status", "unknown")
    plan_review_status = event.get("plan_review_status", "unknown")

    deviation_attributes = _measurement_attributes(
        "PicoT PV afwijking actueel",
        "mdi:chart-line-variant",
        "%",
        event,
    )
    deviation_attributes.update(
        {
            "expected_power_w": event.get("pv_expected_power_w"),
            "actual_power_w": event.get("pv_actual_power_w"),
            "deviation_w": event.get("pv_power_deviation_w"),
            "comparison_status": event.get("pv_forecast_comparison_status"),
        }
    )

    rolling_attributes = _measurement_attributes(
        "PicoT PV afwijking rolling",
        "mdi:chart-bell-curve-cumulative",
        "%",
        event,
    )
    rolling_attributes.update(
        {
            "threshold_percent": event.get("pv_deviation_threshold_percent"),
            "window_seconds": event.get("pv_deviation_window_seconds"),
            "minimum_history_seconds": event.get(
                "pv_deviation_minimum_history_seconds"
            ),
            "history_seconds": event.get("pv_deviation_history_seconds"),
            "sample_count": event.get("pv_deviation_sample_count"),
            "evaluator_status": evaluator_status,
            "replan_candidate": replan_candidate,
        }
    )

    replan_attributes: dict[str, object] = {
        "friendly_name": "PicoT replan candidate",
        "icon": "mdi:source-branch-refresh",
        "evaluator_status": evaluator_status,
        "rolling_deviation_percent": event.get("pv_rolling_deviation_percent"),
        "threshold_percent": event.get("pv_deviation_threshold_percent"),
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }

    review_attributes: dict[str, object] = {
        "friendly_name": "PicoT Plan Review",
        "icon": "mdi:clipboard-search-outline",
        "outcome": event.get("plan_review_outcome"),
        "action": event.get("plan_review_action"),
        "trigger": event.get("plan_review_trigger"),
        "feasibility_scope": event.get("plan_review_feasibility_scope"),
        "control_change_allowed": event.get(
            "plan_review_control_change_allowed"
        ),
        "limitation": event.get("plan_review_limitation"),
        "grid_import_w": event.get("plan_review_grid_import_w"),
        "grid_export_w": event.get("plan_review_grid_export_w"),
        "battery_soc_percent": event.get("plan_review_battery_soc_percent"),
        "battery_charge_power_w": event.get(
            "plan_review_battery_charge_power_w"
        ),
        "battery_discharge_power_w": event.get(
            "plan_review_battery_discharge_power_w"
        ),
        "telemetry_updated_at": event.get("telemetry_updated_at"),
    }

    control_allowed = event.get("plan_review_control_change_allowed") is True
    states: DashboardStates = {
        "sensor.picot_pv_deviation_current": {
            "state": event.get("pv_power_deviation_percent", "unknown"),
            "attributes": deviation_attributes,
        },
        "sensor.picot_pv_deviation_rolling": {
            "state": event.get("pv_rolling_deviation_percent", "unknown"),
            "attributes": rolling_attributes,
        },
        "sensor.picot_pv_deviation_status": {
            "state": evaluator_status,
            "attributes": {
                "friendly_name": "PicoT PV deviation status",
                "icon": "mdi:weather-partly-cloudy",
                "telemetry_updated_at": event.get("telemetry_updated_at"),
            },
        },
        "binary_sensor.picot_replan_candidate": {
            "state": "on" if replan_candidate else "off",
            "attributes": replan_attributes,
        },
        "sensor.picot_plan_review_status": {
            "state": plan_review_status,
            "attributes": review_attributes,
        },
        "binary_sensor.picot_plan_review_control_change_allowed": {
            "state": "on" if control_allowed else "off",
            "attributes": {
                "friendly_name": "PicoT Plan Review control change allowed",
                "icon": "mdi:toggle-switch-outline",
                "telemetry_updated_at": event.get("telemetry_updated_at"),
            },
        },
    }
    for minutes in ENERGY_WINDOWS_MINUTES:
        states[f"sensor.picot_pv_energy_deviation_{minutes}m"] = _energy_window_state(
            event, minutes
        )
    return states


def publish_diagnostics_dashboard_states(
    event: dict[str, object],
    token: str,
    *,
    opener: Callable[..., object] = urlopen,
) -> None:
    """Publish diagnostics entities through the Home Assistant REST API."""

    for entity_id, payload in diagnostics_dashboard_states(event).items():
        request = Request(
            f"{SUPERVISOR_BASE_URL}/api/states/{entity_id}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
        status = getattr(response, "status", None)
        if not isinstance(status, int) or status not in {200, 201}:
            raise RuntimeError(
                f"Home Assistant rejected diagnostics dashboard state {entity_id}: {status}."
            )
