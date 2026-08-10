"""Deterministic Phase 1 plan-review foundation for PEP-RP-001.

A deviation candidate opens a review; it never authorises a control action. Phase 1
is deliberately conservative: until trajectory and expected-balance models exist,
the existing plan is kept and the limited feasibility scope is made explicit.
"""

from __future__ import annotations

from typing import Any


def evaluate_plan_review(event: dict[str, Any]) -> dict[str, object]:
    """Return a no-action Phase 1 plan-review decision."""

    candidate = event.get("pv_deviation_replan_candidate") is True
    if not candidate:
        return {
            "plan_review_status": "not_requested",
            "plan_review_outcome": None,
            "plan_review_action": "keep_current_plan",
            "plan_review_feasibility_scope": "phase1_observation_only",
            "plan_review_control_change_allowed": False,
        }

    return {
        "plan_review_status": "completed",
        "plan_review_outcome": "current_plan_still_feasible",
        "plan_review_action": "keep_current_plan",
        "plan_review_feasibility_scope": "phase1_observation_only",
        "plan_review_control_change_allowed": False,
        "plan_review_trigger": "pv_deviation_replan_candidate",
        "plan_review_pv_deviation_status": event.get("pv_deviation_evaluator_status"),
        "plan_review_pv_rolling_deviation_percent": event.get(
            "pv_rolling_deviation_percent"
        ),
        "plan_review_grid_import_w": event.get("grid_import_w"),
        "plan_review_grid_export_w": event.get("grid_export_w"),
        "plan_review_battery_soc_percent": event.get("zendure_soc_percent"),
        "plan_review_battery_charge_power_w": event.get("zendure_charge_power_w"),
        "plan_review_battery_discharge_power_w": event.get(
            "zendure_discharge_power_w"
        ),
        "plan_review_limitation": (
            "Phase 1 does not yet project target SoC, expected load/grid balance, "
            "or alternative plans; therefore it cannot authorise a control change."
        ),
    }


def plan_review_log_event(event: dict[str, Any]) -> dict[str, object]:
    """Return compact, persistent evidence for a plan review."""

    return {
        "event": "picot_plan_review",
        "status": event.get("plan_review_status"),
        "outcome": event.get("plan_review_outcome"),
        "action": event.get("plan_review_action"),
        "feasibility_scope": event.get("plan_review_feasibility_scope"),
        "control_change_allowed": event.get("plan_review_control_change_allowed"),
        "trigger": event.get("plan_review_trigger"),
        "pv_deviation_status": event.get("plan_review_pv_deviation_status"),
        "pv_rolling_deviation_percent": event.get(
            "plan_review_pv_rolling_deviation_percent"
        ),
        "grid_import_w": event.get("plan_review_grid_import_w"),
        "grid_export_w": event.get("plan_review_grid_export_w"),
        "battery_soc_percent": event.get("plan_review_battery_soc_percent"),
        "battery_charge_power_w": event.get("plan_review_battery_charge_power_w"),
        "battery_discharge_power_w": event.get(
            "plan_review_battery_discharge_power_w"
        ),
        "limitation": event.get("plan_review_limitation"),
        "observed_at": event.get("telemetry_updated_at"),
    }
