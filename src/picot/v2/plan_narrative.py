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
    result["operation"] = _operation_summary(run, plans, paths)
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

def _operation_summary(
    run: CanonicalPipelineRun, plans: list[Any], paths: dict[str, Any],
) -> dict[str, Any] | None:
    """Describe support/floor timing from the admitted plan, without replanning."""
    if len(plans) != 1:
        return None
    plan = plans[0]
    now = run.planning_input.captured_at
    segments = sorted((s for s in plan.segments if s.ends_at > now),
                      key=lambda s: s.starts_at)
    if not segments:
        return None
    current = next((s for s in segments if s.starts_at <= now < s.ends_at), None)
    first = current or segments[0]
    constraint = first.soc_constraint
    if constraint is None:
        return None
    minimum = constraint.minimum
    state = next((s for s in run.planning_input.current_storage_states
                  if s.execution_scope_id == plan.execution_scope_id), None)
    charging = [s for s in segments if s.main_assignment_id is not None or
                s.primitive.value in {"charge_at_power", "balance_charge_only"}]
    charge_at = max(now, charging[0].starts_at) if charging else None
    support_modes = {"balance_discharge_only", "balance_bidirectional"}
    supporting = current is not None and current.primitive.value in support_modes
    support_until = current.ends_at if supporting and current is not None else None
    if support_until is not None:
        for segment in segments:
            if segment.starts_at < support_until:
                continue
            if (segment.starts_at != support_until or segment.main_assignment_id is not None
                    or segment.primitive.value not in support_modes):
                break
            support_until = segment.ends_at
    path = paths.get(plan.winning_energy_path_id)
    floor_at = None
    status = "unknown" if path is None or not path.projected_states else "not_projected"
    if (state is not None and state.current_soc <= minimum + 1e-9
            and current is not None and current.main_assignment_id is None
            and current.primitive.value in support_modes | {"standby"}):
        floor_at, status = now, "reached"
    elif path is not None:
        for projected in sorted(path.projected_states, key=lambda s: s.at):
            if (projected.at <= now or (charge_at is not None and projected.at > charge_at)
                    or projected.battery_soc is None or projected.battery_soc > minimum + 1e-9):
                continue
            segment = next((s for s in segments
                            if s.starts_at < projected.at <= s.ends_at), None)
            if (segment is not None and segment.main_assignment_id is None
                    and segment.primitive.value in support_modes):
                floor_at, status = projected.at, "projected"
                break
    if support_until is not None and floor_at is not None:
        support_until = min(support_until, floor_at)
    return {"minimum_soc_percent": minimum * 100,
            "floor_status": status,
            "floor_at": floor_at.isoformat() if floor_at else None,
            "support_until": support_until.isoformat() if support_until else None,
            "next_charge_at": charge_at.isoformat() if charge_at else None}
