"""Read-only physical description of the admitted execution plans."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from picot.v2.contracts import CanonicalPipelineRun


def build_plan_narrative(run: CanonicalPipelineRun) -> dict[str, Any]:
    """Report producer-owned flows; never infer a new plan or source allocation."""
    now = run.planning_input.captured_at
    context = run.planning_input.daily_charge_context
    zone = ZoneInfo(context.timezone if context else "Europe/Amsterdam")
    result: dict[str, Any] = {
        "days": [], "windows": [], "projected_at": now.isoformat(),
        "energy_available": False,
        "cost_projection": None,
    }
    if run.evaluation.status == "fallback_active":
        return result
    plans = [p for p in run.execution_plan_set.plans if p.valid_until > now]
    paths = {p.path_id: p for p in run.candidate_set.energy_paths}
    admitted = {p.winning_energy_path_id for p in plans}
    # Windows remain authoritative even on a normal retained observation that
    # intentionally performs no fresh physical simulation.
    windows: list[dict[str, Any]] = []
    for plan in plans:
        for segment in plan.segments:
            if segment.ends_at <= now:
                continue
            kind = {"charge_at_power": "grid_charge", "standby": "standby"}.get(
                segment.primitive.value)
            if kind == "grid_charge" and (
                segment.charge_source_policy is None
                or not segment.charge_source_policy.permits_grid_import
            ):
                continue
            if kind is None:
                continue
            windows.append({"kind": kind, "starts_at": segment.starts_at.isoformat(),
                            "ends_at": segment.ends_at.isoformat()})
    windows.sort(key=lambda w: (w["starts_at"], w["ends_at"], w["kind"]))
    merged: list[dict[str, Any]] = []
    for window in windows:
        if merged and window == merged[-1]:
            continue
        if (merged and merged[-1]["kind"] == window["kind"]
                and merged[-1]["ends_at"] == window["starts_at"]):
            merged[-1]["ends_at"] = window["ends_at"]
        else:
            merged.append(dict(window))
    result["windows"] = merged
    if len(admitted) != 1 or not admitted.issubset(paths):
        return result
    active_path = paths[next(iter(admitted))]
    import_cost = active_path.projected_import_cost_eur
    export_revenue = active_path.projected_export_revenue_eur
    if (active_path.snapshot_id == run.planning_input.snapshot_id
            and active_path.cost_starts_at == now
            and active_path.cost_ends_at is not None and active_path.cost_ends_at > now
            and import_cost is not None and isfinite(import_cost)
            and export_revenue is not None and isfinite(export_revenue)):
        result["cost_projection"] = {
            "starts_at": now.isoformat(),
            "ends_at": active_path.cost_ends_at.isoformat(),
            "import_cost_eur": import_cost,
            "export_revenue_eur": export_revenue,
            "total_cost_eur": import_cost - export_revenue,
        }
    days: dict[str, dict[str, Any]] = {}

    def day_for(at: datetime) -> dict[str, Any]:
        key = at.astimezone(zone).date().isoformat()
        return days.setdefault(key, {"date": key, "pv_charge_kwh": None,
            "pv_other_kwh": None, "grid_charge_kwh": None, "full_at": None,
            "starts_at": None, "ends_at": None})

    available = True
    for path_id in sorted(admitted):
        path = paths[path_id]
        states = sorted(path.projected_states, key=lambda s: s.at)
        future = [s for s in states if s.at > now]
        flow_states = [s for s in future if s.flow_starts_at is not None]
        if not flow_states or len(flow_states) != len(future):
            available = False
        for state in flow_states:
            values = (state.pv_storage_input_wh, state.pv_other_wh,
                      state.grid_storage_input_wh)
            if any(v is None or not isfinite(v) or v < 0 for v in values):
                available = False
                continue
            assert state.flow_starts_at is not None
            original_start = state.flow_starts_at.astimezone(UTC)
            if state.at <= original_start:
                available = False
                continue
            start = max(original_start, now.astimezone(UTC))
            seconds = (state.at - original_start).total_seconds()
            while start < state.at:
                next_date = start.astimezone(zone).date() + timedelta(days=1)
                midnight = datetime.combine(next_date, time.min, zone).astimezone(UTC)
                end = min(midnight, state.at)
                day = day_for(start)
                fraction = (end - start).total_seconds() / seconds / 1000
                for key, value in zip(("pv_charge_kwh", "pv_other_kwh", "grid_charge_kwh"),
                                      values, strict=True):
                    assert value is not None
                    day[key] = (day[key] or 0.0) + value * fraction
                day["starts_at"] = min(day["starts_at"] or start.isoformat(), start.isoformat())
                day["ends_at"] = max(day["ends_at"] or end.isoformat(), end.isoformat())
                start = end
        # A deadline or an effective maximum below 100% is not a 100% forecast.
        # Show the first future checkpoint where the physical path reaches 100%.
        scope = next(p.execution_scope_id for p in plans if p.winning_energy_path_id == path_id)
        previous_soc = next((s.current_soc for s in run.planning_input.current_storage_states
                             if s.execution_scope_id == scope), None)
        full = None
        for state in future:
            if state.battery_soc is None:
                continue
            if (state.battery_soc >= 1.0 - 1e-9 and previous_soc is not None
                    and previous_soc < 1.0 - 1e-9):
                full = state
                break
            previous_soc = state.battery_soc
        if full is not None:
            day = day_for(full.at)
            day["full_at"] = min(day["full_at"] or full.at.isoformat(), full.at.isoformat())
    if not available:
        for day in days.values():
            for key in ("pv_charge_kwh", "pv_other_kwh", "grid_charge_kwh"):
                day[key] = None
    result["energy_available"] = available
    result["days"] = [days[key] for key in sorted(days)]
    return result

