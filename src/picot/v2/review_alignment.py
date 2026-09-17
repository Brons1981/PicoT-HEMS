"""Observer-only energy balance over matching UTC clock quarters.

Integrate each Recorder state-held power independently over identical boundaries.
This derives interval energy, not instantaneous load or independently measured
household energy. Missing/negative evidence is never replaced by zero. No output
from here may feed MEP or certify the strict measured replay.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from picot.v2.power_history import PowerHistorySeries, PowerHistorySnapshot

FLOW_SIGNS = {
    "pv_generation": 1,
    "grid_import": 1,
    "grid_export": -1,
    "battery_charge": -1,
    "battery_discharge": 1,
}
METHOD = "review-clock-quarter-power-integration:v1"
QUARTER_SECONDS = 900


def _integrals(
    series: PowerHistorySeries,
    bounds: list[datetime],
) -> tuple[list[float | None], list[str | None]]:
    points = sorted(series.points, key=lambda p: p.sampled_at)
    values: list[float | None] = []
    reasons: list[str | None] = []
    if series.history_semantics != "state_hold":
        return ([None] * (len(bounds) - 1), ["unsupported_history_semantics"] * (len(bounds) - 1))
    index = -1
    for start, end in zip(bounds, bounds[1:], strict=False):
        at, energy, reason = start, 0.0, None
        while at < end:
            while index + 1 < len(points) and points[index + 1].sampled_at <= at:
                index += 1
            next_at = min(end, points[index + 1].sampled_at) if index + 1 < len(points) else end
            if index < 0:
                reason = "measurement_start_missing"
            else:
                power = points[index].power_w
                if not isfinite(power) or power < 0:
                    reason = "measurement_unavailable"
                else:
                    energy += power * (next_at - at).total_seconds() / 3600
            at = next_at
        values.append(energy if reason is None else None)
        reasons.append(reason)
    return values, reasons


def aligned_measurements(history: PowerHistorySnapshot) -> dict[str, Any]:
    """Bounded, explicit derived evidence; never fill a missing measured series."""
    result: dict[str, Any] = {
        "method_version": METHOD,
        "status": "unavailable",
        "observer_only": True,
        "selection_permitted": False,
        "strict_replay_permitted": False,
        "household_evidence_kind": "derived_from_integrated_power",
        "uncertainty": "sensor_time_alignment_and_within_quarter_flows_not_resolved",
        "interval_seconds": QUARTER_SECONDS,
        "starts_at": history.starts_at.isoformat(),
        "ends_at": history.ends_at.isoformat(),
        "intervals": [],
    }
    if history.status != "available" or history.error is not None:
        return dict(result, reason="history_unavailable")
    if history.ends_at <= history.starts_at or history.ends_at - history.starts_at > timedelta(
        hours=26
    ):
        return dict(result, reason="alignment_horizon_invalid")
    counts = Counter(s.role for s in history.series)
    invalid_roles = [role for role in FLOW_SIGNS if counts[role] != 1]
    if invalid_roles:
        return dict(result, reason="missing_or_ambiguous_flow_series", invalid_roles=invalid_roles)
    bounds = [history.starts_at]
    tick = (int(history.starts_at.timestamp()) // QUARTER_SECONDS + 1) * QUARTER_SECONDS
    while tick < history.ends_at.timestamp():
        bounds.append(datetime.fromtimestamp(tick, UTC))
        tick += QUARTER_SECONDS
    bounds.append(history.ends_at)
    by_role = {s.role: s for s in history.series}
    result["sources"] = {role: by_role[role].source_entity_id for role in FLOW_SIGNS}
    integrated = {role: _integrals(by_role[role], bounds) for role in FLOW_SIGNS}
    intervals: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(zip(bounds, bounds[1:], strict=False)):
        energy = {role: integrated[role][0][index] for role in FLOW_SIGNS}
        errors = {
            role: integrated[role][1][index]
            for role in FLOW_SIGNS
            if integrated[role][1][index] is not None
        }
        balance = (
            None
            if errors
            else sum(
                FLOW_SIGNS[role] * value for role, value in energy.items() if value is not None
            )
        )
        reason = (
            "source_coverage_incomplete"
            if errors
            else (
                "negative_household_energy_balance" if balance is not None and balance < 0 else None
            )
        )
        intervals.append(
            {
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "status": "invalid" if reason else "derived",
                "reason": reason,
                "source_errors": errors,
                "energy_wh": energy,
                "household_balance_wh": balance,
                "household_energy_wh": balance if reason is None else None,
            }
        )
    valid = [i for i in intervals if i["status"] == "derived"]
    invalid = [i for i in intervals if i["status"] == "invalid"]
    return dict(
        result,
        status="partial" if invalid else "derived",
        reason=None,
        intervals=intervals,
        derived_interval_count=len(valid),
        invalid_interval_count=len(invalid),
        derived_household_energy_wh=sum(i["household_energy_wh"] for i in valid),
        total_household_energy_wh=None if invalid else sum(i["household_energy_wh"] for i in valid),
        invalid_intervals=[
            {k: i[k] for k in ("starts_at", "ends_at", "reason", "source_errors")}
            for i in invalid[:20]
        ],
        omitted_invalid_interval_count=max(0, len(invalid) - 20),
    )
