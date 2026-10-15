"""Display-only gross self-consumption value; never a settlement or planner input."""

from datetime import timedelta
from math import isfinite

from picot.v2.contracts import PlanningInputSnapshot


def estimated_stored_energy_value(
    snapshot: PlanningInputSnapshot, discharge_efficiency: float,
) -> dict[str, object]:
    now = snapshot.captured_at
    end = now + timedelta(hours=24)
    result: dict[str, object] = {
        "status": "unavailable", "value_eur": None,
        "captured_at": now.isoformat(), "price_window_ends_at": end.isoformat(),
        "method_version": "stored-energy-self-consumption-24h:v1",
        "observer_only": True, "selection_permitted": False,
    }
    if len(snapshot.current_storage_states) != 1:
        return result
    state = snapshot.current_storage_states[0]
    limits = [item for item in snapshot.storage_physical_limits
              if item.execution_scope_id == state.execution_scope_id]
    # An unchanged HA value may have an old last_updated but a fresh state read.
    observed_at = state.state_read_at or state.measured_at
    if len(limits) != 1 or not 0 <= (now - observed_at).total_seconds() <= 900:
        return result
    minimum = limits[0].minimum_soc
    if (not all(isfinite(v) for v in (
        state.current_soc, state.usable_capacity_wh, minimum, discharge_efficiency,
    )) or not 0 <= minimum <= 1 or not 0 <= state.current_soc <= 1
        or state.usable_capacity_wh <= 0 or not 0 < discharge_efficiency <= 1):
        return result
    cursor = now
    weighted_price = 0.0
    for point in sorted(snapshot.price_points, key=lambda p: p.starts_at):
        start, stop = max(now, point.starts_at), min(end, point.ends_at)
        if stop <= start:
            continue
        if start != cursor or not isfinite(point.value_eur_per_kwh):
            return result
        weighted_price += (stop - start).total_seconds() * point.value_eur_per_kwh
        cursor = stop
    if cursor != end:
        return result
    rate = weighted_price / (end - now).total_seconds()
    deliverable_kwh = (
        max(0.0, state.current_soc - minimum) * state.usable_capacity_wh
        * discharge_efficiency / 1000
    )
    result.update({
        "status": "estimated", "value_eur": round(deliverable_kwh * rate, 4),
        "deliverable_energy_kwh": deliverable_kwh,
        "average_import_eur_per_kwh": rate,
    })
    return result
