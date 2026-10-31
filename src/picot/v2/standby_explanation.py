"""Attribute a total route difference only to an evidenced standby choice."""

from datetime import datetime
from math import isfinite

from picot.v2.contracts import CanonicalPipelineRun


def standby_comparison(
    run: CanonicalPipelineRun, decision: dict[str, object],
) -> dict[str, object] | None:
    """Never turn a general route saving or acquisition rate into standby savings."""
    costs = [decision.get(k) for k in ("incumbent_cost_eur", "alternative_cost_eur")]
    if not all(isinstance(v, (float, int)) and isfinite(v) for v in costs):
        return None
    candidates = {c.candidate_id: c.energy_path_id for c in run.candidate_set.candidates}
    paths = {p.path_id: p for p in run.candidate_set.energy_paths}
    admitted = {p.winning_energy_path_id for p in run.execution_plan_set.plans}
    if len(admitted) != 1 or decision.get("status") not in {"retained", "replaced"}:
        return None
    retained = decision["status"] == "retained"
    active_id = decision.get("incumbent_candidate_id" if retained else "alternative_candidate_id")
    other_id = decision.get("alternative_candidate_id" if retained else "incumbent_candidate_id")
    active = paths.get(candidates.get(str(active_id), ""))
    other = paths.get(candidates.get(str(other_id), ""))
    if active is None or other is None or active.path_id not in admitted:
        return None
    if (not active.segments or not other.segments
            or not active.projected_states or not other.projected_states):
        return None
    start_a = min(s.starts_at for s in active.segments)
    start_b = min(s.starts_at for s in other.segments)
    end_time_a = max(s.ends_at for s in active.segments)
    end_time_b = max(s.ends_at for s in other.segments)
    if start_a != start_b or end_time_a != end_time_b:
        return None
    end_a, end_b = active.projected_states[-1], other.projected_states[-1]
    if (end_a.at != end_time_a or end_b.at != end_time_b
            or end_a.storage_energy_wh is None or end_b.storage_energy_wh is None
            or abs(end_a.storage_energy_wh - end_b.storage_energy_wh) > 1e-6):
        return None
    # Compare actions at the union of boundaries, independent of segment splitting.
    bounds = sorted({start_a, end_time_a,
                     *(s.starts_at for s in active.segments + other.segments),
                     *(s.ends_at for s in active.segments + other.segments)})
    windows: list[tuple[datetime, datetime]] = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        a = next((s for s in active.segments if s.starts_at <= start < s.ends_at), None)
        b = next((s for s in other.segments if s.starts_at <= start < s.ends_at), None)
        if a is None or b is None or a.execution_scope_id != b.execution_scope_id:
            return None
        signature_a = (a.primitive, a.requested_power_w, a.charge_source_policy, a.soc_constraint)
        signature_b = (b.primitive, b.requested_power_w, b.charge_source_policy, b.soc_constraint)
        if signature_a == signature_b:
            continue
        if (a.primitive.value != "standby"
                or b.primitive.value not in {"balance_bidirectional", "balance_discharge_only"}):
            return None
        if windows and windows[-1][1] == start:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((start, end))
    if len(windows) != 1:
        return None
    incumbent, alternative = costs
    assert isinstance(incumbent, (int, float)) and isinstance(alternative, (int, float))
    benefit = alternative - incumbent if retained else incumbent - alternative
    if benefit <= 0:
        return None
    return {"starts_at": windows[0][0].isoformat(), "ends_at": windows[0][1].isoformat(),
            "benefit_eur": benefit}
