"""Publish read-only PicoT planner diagnostics for Home Assistant."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SUPERVISOR_BASE_URL = "http://supervisor/core"
HTTP_TIMEOUT_SECONDS = 10.0
ENERGY_WINDOWS_MINUTES = (15, 30, 60)

DashboardPayload = dict[str, object]
DashboardStates = dict[str, DashboardPayload]


class DiagnosticsPublishError(RuntimeError):
    """Context-rich Home Assistant diagnostics publication failure."""

    def __init__(
        self,
        *,
        entity_id: str,
        endpoint: str,
        payload_state: object,
        status: int | None,
        cause: Exception | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.endpoint = endpoint
        self.payload_state = payload_state
        self.status = status
        self.cause = cause
        detail = str(cause) if cause is not None else "Home Assistant rejected state update"
        super().__init__(
            f"HA diagnostics publish failed entity_id={entity_id} endpoint={endpoint} "
            f"http_status={status} payload_state={payload_state!r}: {detail}"
        )


def _safe_state(value: object) -> object:
    return "unknown" if value is None else value


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


def _energy_window_state(event: dict[str, object], minutes: int) -> DashboardPayload:
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
            "status": _safe_state(event.get(f"{prefix}_status")),
            "solcast_expected_kwh": event.get(f"{prefix}_expected_kwh"),
            "goodwe_actual_kwh": event.get(f"{prefix}_actual_kwh"),
            "coverage_seconds": event.get(f"{prefix}_coverage_seconds"),
            "replan_input": False,
        }
    )
    return {
        "state": _safe_state(event.get(f"{prefix}_deviation_percent")),
        "attributes": attributes,
    }


def diagnostics_dashboard_states(event: dict[str, object]) -> DashboardStates:
    """Build semantic states for the Developer/Diagnostics View."""

    replan_candidate = event.get("pv_deviation_replan_candidate") is True
    evaluator_status = _safe_state(event.get("pv_deviation_evaluator_status"))
    plan_review_status = _safe_state(event.get("plan_review_status"))

    deviation_attributes = _measurement_attributes(
        "PicoT PV afwijking actueel", "mdi:chart-line-variant", "%", event
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
        "PicoT PV afwijking rolling", "mdi:chart-bell-curve-cumulative", "%", event
    )
    rolling_attributes.update(
        {
            "threshold_percent": event.get("pv_deviation_threshold_percent"),
            "window_seconds": event.get("pv_deviation_window_seconds"),
            "minimum_history_seconds": event.get("pv_deviation_minimum_history_seconds"),
            "history_seconds": event.get("pv_deviation_history_seconds"),
            "sample_count": event.get("pv_deviation_sample_count"),
            "evaluator_status": evaluator_status,
            "replan_candidate": replan_candidate,
        }
    )

    states: DashboardStates = {
        "sensor.picot_pv_deviation_current": {
            "state": _safe_state(event.get("pv_power_deviation_percent")),
            "attributes": deviation_attributes,
        },
        "sensor.picot_pv_deviation_rolling": {
            "state": _safe_state(event.get("pv_rolling_deviation_percent")),
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
            "attributes": {
                "friendly_name": "PicoT replan candidate",
                "icon": "mdi:source-branch-refresh",
                "evaluator_status": evaluator_status,
                "rolling_deviation_percent": event.get("pv_rolling_deviation_percent"),
                "threshold_percent": event.get("pv_deviation_threshold_percent"),
                "telemetry_updated_at": event.get("telemetry_updated_at"),
            },
        },
        "sensor.picot_plan_review_status": {
            "state": plan_review_status,
            "attributes": {
                "friendly_name": "PicoT Plan Review",
                "icon": "mdi:clipboard-search-outline",
                "outcome": event.get("plan_review_outcome"),
                "action": event.get("plan_review_action"),
                "trigger": event.get("plan_review_trigger"),
                "feasibility_scope": event.get("plan_review_feasibility_scope"),
                "control_change_allowed": event.get("plan_review_control_change_allowed"),
                "limitation": event.get("plan_review_limitation"),
                "grid_import_w": event.get("plan_review_grid_import_w"),
                "grid_export_w": event.get("plan_review_grid_export_w"),
                "battery_soc_percent": event.get("plan_review_battery_soc_percent"),
                "battery_charge_power_w": event.get("plan_review_battery_charge_power_w"),
                "battery_discharge_power_w": event.get("plan_review_battery_discharge_power_w"),
                "telemetry_updated_at": event.get("telemetry_updated_at"),
            },
        },
        "binary_sensor.picot_plan_review_control_change_allowed": {
            "state": "on" if event.get("plan_review_control_change_allowed") is True else "off",
            "attributes": {
                "friendly_name": "PicoT Plan Review control change allowed",
                "icon": "mdi:toggle-switch-outline",
                "telemetry_updated_at": event.get("telemetry_updated_at"),
            },
        },
        "sensor.picot_price_entry_observation": {
            "state": _safe_state(event.get("price_entry_observation_status")),
            "attributes": {
                "friendly_name": "PicoT prijs-start observatie",
                "icon": "mdi:clock-check-outline",
                "observation_only": True,
                "replan_input": False,
                "opportunity_rank": event.get("price_entry_opportunity_rank"),
                "opportunity_starts_at": event.get("price_entry_opportunity_starts_at"),
                "opportunity_ends_at": event.get("price_entry_opportunity_ends_at"),
                "reference_starts_at": event.get("price_entry_reference_starts_at"),
                "reference_price_eur_per_kwh": event.get(
                    "price_entry_reference_price_eur_per_kwh"
                ),
                "better_later_price_exists": event.get(
                    "price_entry_better_later_price_exists"
                ),
                "best_later_starts_at": event.get("price_entry_best_later_starts_at"),
                "best_later_price_eur_per_kwh": event.get(
                    "price_entry_best_later_price_eur_per_kwh"
                ),
                "best_later_saving_eur_per_kwh": event.get(
                    "price_entry_best_later_saving_eur_per_kwh"
                ),
                "alternatives": event.get("price_entry_alternatives", []),
                "limitation": event.get("price_entry_limitation"),
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
        endpoint = f"/api/states/{entity_id}"
        request = Request(
            f"{SUPERVISOR_BASE_URL}{endpoint}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = opener(request, timeout=HTTP_TIMEOUT_SECONDS)
        except HTTPError as exc:
            raise DiagnosticsPublishError(
                entity_id=entity_id,
                endpoint=endpoint,
                payload_state=payload.get("state"),
                status=exc.code,
                cause=exc,
            ) from exc
        status = getattr(response, "status", None)
        if not isinstance(status, int) or status not in {200, 201}:
            raise DiagnosticsPublishError(
                entity_id=entity_id,
                endpoint=endpoint,
                payload_state=payload.get("state"),
                status=status if isinstance(status, int) else None,
            )
