"""Measured display amounts and their dependencies; no planning authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import Any

from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot
from picot.v2.review_measurements import measurement_coverage

SETTLEMENT_ROLES = frozenset({
    "pv_generation", "household_load", "grid_import", "grid_export",
    "battery_charge", "battery_discharge",
})
METRIC_ROLES = {
    "grid_import_cost_eur": frozenset({"grid_import"}),
    "grid_export_revenue_eur": frozenset({"grid_export"}),
    "actual_energy_cost_eur": frozenset({"grid_import", "grid_export"}),
    "battery_wear_eur": frozenset({"battery_discharge"}),
    **{name: SETTLEMENT_ROLES for name in (
        "net_total_energy_value_eur", "gross_battery_value_eur",
        "net_battery_value_eur", "gross_picot_value_eur", "net_picot_value_eur",
    )},
}
PriceSegments = list[tuple[datetime, datetime, float, float]]


def financial_metric_value(day: Mapping[str, Any], name: str) -> float | None:
    """Read new evidence when present, retaining old stored-day compatibility."""
    metrics = day.get("financial_metrics")
    if isinstance(metrics, dict):
        metric = metrics.get("values", {}).get(name, {})
        value = metric.get("value_eur") if metric.get("status") == "available" else None
    else:
        value = day.get(name) if day.get("status") == "available" else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def _priced_power(series: PowerHistorySeries, segments: PriceSegments, *, export: bool) -> float:
    """Integrate validated state-held power across tariffs in one ordered pass."""
    points = sorted(series.points, key=lambda point: point.sampled_at)
    cursor = segments[0][0]
    index = 0
    held = None
    while index < len(points) and points[index].sampled_at <= cursor:
        held = points[index]
        index += 1
    if held is None:
        raise ValueError("priced power requires a measured start anchor")
    total = 0.0
    for start, end, import_rate, export_rate in segments:
        cursor = start
        watt_seconds = 0.0
        while index < len(points) and points[index].sampled_at < end:
            point = points[index]
            watt_seconds += held.power_w * (point.sampled_at - cursor).total_seconds()
            held, cursor = point, point.sampled_at
            index += 1
        watt_seconds += held.power_w * (end - cursor).total_seconds()
        total += watt_seconds / 3_600_000.0 * (export_rate if export else import_rate)
    return total


def build_financial_metrics(
    *, history: PowerHistorySnapshot, settlement: Mapping[str, Any],
    price_segments: PriceSegments, wear_rate: float,
    expected_starts_at: datetime, expected_ends_at: datetime,
) -> dict[str, Any]:
    """Gate each amount on its own sources, preserving the legacy inventory path."""
    coverage = {
        role: value for role, value in measurement_coverage(history).items()
        if role in SETTLEMENT_ROLES
    }
    # An unavailable observation exactly at the right boundary has no duration
    # in this settlement. It must not invalidate the preceding measured energy.
    for value in coverage.values():
        value["gaps"] = [gap for gap in value["gaps"] if gap["duration_seconds"] > 0]
        value["gap_count"] = len(value["gaps"]) + value["omitted_gap_count"]
    by_role = {series.role: series for series in history.series}
    history_reason = None
    if history.status != "available" or history.error is not None:
        history_reason = "measurement_history_unavailable"
    elif (history.starts_at != expected_starts_at or history.ends_at != expected_ends_at
          or history.ends_at <= history.starts_at):
        history_reason = "measurement_period_mismatch"

    measured: dict[str, float] = {}
    if history_reason is None:
        for name, role, export in (
            ("grid_import_cost_eur", "grid_import", False),
            ("grid_export_revenue_eur", "grid_export", True),
            ("battery_wear_eur", "battery_discharge", False),
        ):
            if coverage[role]["gap_count"]:
                continue
            segments = (
                [(history.starts_at, history.ends_at, wear_rate, wear_rate)]
                if name == "battery_wear_eur" else price_segments
            )
            if segments:
                measured[name] = _priced_power(by_role[role], segments, export=export)
        if "grid_import_cost_eur" in measured and "grid_export_revenue_eur" in measured:
            measured["actual_energy_cost_eur"] = (
                measured["grid_import_cost_eur"] - measured["grid_export_revenue_eur"]
            )

    values = {}
    for name, required_roles in METRIC_ROLES.items():
        missing = sorted(role for role in required_roles if coverage[role]["gap_count"])
        reason = history_reason
        if reason is None and missing:
            reason = "measurement_coverage_incomplete"
        if reason is None and name != "battery_wear_eur" and not price_segments:
            reason = "price_coverage_incomplete"
        amount = None
        if reason is None:
            if name in measured:
                amount = measured[name]
            else:
                amount = financial_metric_value(settlement, name)
            if amount is None or not isfinite(amount):
                amount = None
                reason = settlement.get("reason") or "financial_result_unavailable"
        values[name] = {
            "status": "available" if reason is None else "incomplete",
            "value_eur": round(amount, 4) if reason is None and amount is not None else None,
            "reason": reason, "required_roles": sorted(required_roles),
            "missing_roles": missing,
        }
    available_count = sum(value["status"] == "available" for value in values.values())
    return {
        "method_version": "financial-metric-availability:v1",
        "status": ("available" if available_count == len(values)
                   else "partial" if available_count else "incomplete"),
        "starts_at": history.starts_at.isoformat(), "ends_at": history.ends_at.isoformat(),
        "values": values, "measurement_coverage": coverage,
        "observer_only": True, "selection_permitted": False,
    }
