"""Deterministic comparison between Solcast expected PV and actual GoodWe PV.

This module is observation-only.  It deliberately does not influence planner
execution yet; it exposes the evidence needed for the next replanning step.
"""

from __future__ import annotations

from typing import Any


def add_pv_forecast_comparison_fields(event: dict[str, Any]) -> None:
    """Add current PV forecast-vs-actual fields to one telemetry snapshot."""

    expected = event.get("solcast_current_expected_power_w")
    actual = event.get("goodwe_solar_power_w")
    solcast_available = event.get("solcast_status") == "available"
    goodwe_available = event.get("goodwe_status") == "available"

    if (
        not solcast_available
        or not goodwe_available
        or not isinstance(expected, (int, float))
        or isinstance(expected, bool)
        or not isinstance(actual, (int, float))
        or isinstance(actual, bool)
    ):
        event.update(
            {
                "pv_forecast_comparison_status": "unavailable",
                "pv_expected_power_w": None,
                "pv_actual_power_w": None,
                "pv_power_deviation_w": None,
                "pv_power_deviation_percent": None,
                "pv_actual_to_forecast_ratio": None,
            }
        )
        return

    expected_w = float(expected)
    actual_w = float(actual)
    deviation_w = actual_w - expected_w
    if expected_w > 0.0:
        deviation_percent = (deviation_w / expected_w) * 100.0
        ratio = actual_w / expected_w
    else:
        deviation_percent = None
        ratio = None

    event.update(
        {
            "pv_forecast_comparison_status": "available",
            "pv_expected_power_w": expected_w,
            "pv_actual_power_w": actual_w,
            "pv_power_deviation_w": deviation_w,
            "pv_power_deviation_percent": deviation_percent,
            "pv_actual_to_forecast_ratio": ratio,
        }
    )


def pv_forecast_comparison_log_event(event: dict[str, Any]) -> dict[str, object]:
    """Return a compact, traceable log event for PV forecast validation."""

    return {
        "event": "picot_pv_forecast_comparison",
        "status": event.get("pv_forecast_comparison_status"),
        "expected_power_w": event.get("pv_expected_power_w"),
        "actual_power_w": event.get("pv_actual_power_w"),
        "deviation_w": event.get("pv_power_deviation_w"),
        "deviation_percent": event.get("pv_power_deviation_percent"),
        "actual_to_forecast_ratio": event.get("pv_actual_to_forecast_ratio"),
        "solcast_confidence": event.get("solcast_today_confidence"),
        "observed_at": event.get("telemetry_updated_at"),
    }
