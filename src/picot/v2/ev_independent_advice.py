"""Price EV windows independently; only proven surplus PV receives solar credit."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.ev_deadline_advice import _number, _placement_starts, _time
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

METHOD = "ev-grid-and-surplus-pv:v1"


def advise(
    snapshot: PlanningInputSnapshot, request: dict[str, Any],
    conversion_model: StorageConversionModel | None,
    *, selections: dict[str, Any] | None = None,
    execution_not_before: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract": "energy-device-charging-advice:v1",
        "session_id": request.get("session_id"),
        "request_revision": request.get("request_revision"),
        "generated_at": snapshot.captured_at.isoformat(),
        "snapshot_id": snapshot.snapshot_id, "run_id": snapshot.run_id,
        "method_version": METHOD, "status": "blocked", "slots": [],
        "scheduled_energy_wh": 0, "advisory_only": True,
        "selection_scope": "ev_grid_and_surplus_pv",
        "storage_support_allowed": False, "battery_route_changed": False,
        "joint_acceptance_required": False,
    }
    try:
        UUID(str(request.get("session_id")))
        if (request.get("contract") != "energy-device-charging-request:v1"
                or request.get("state") != "requested"
                or type(request.get("request_revision")) is not int
                or request["request_revision"] < 1
                or request.get("evidence_source") != "user_grid_energy_estimate"):
            raise ValueError("invalid_request_contract")
        available, deadline = _time(request.get("available_from")), _time(request.get("ready_by"))
        now = snapshot.captured_at
        if (not available < deadline <= min(available, now) + timedelta(days=7)
                or _time(request.get("evidence_at")) > now):
            raise ValueError("invalid_request_window")
        energy = _number(request.get("remaining_energy_wh"), 0, 88320)
        power = _number(request.get("fixed_power_w"), 100, 3680)
        result.update(required_energy_wh=energy, ready_by=deadline.isoformat())
        start = max(now + timedelta(seconds=120), available)
        duration = timedelta(hours=energy / power)
        if start + duration > deadline:
            result.update(status="infeasible", reason="deadline_capacity_insufficient")
            return result
        if energy == 0:
            result.update(status="ready", reason="no_remaining_energy")
            return result
        policy = snapshot.external_load_policy
        if policy is not None and (policy.power_w > 0 or policy.session_id is not None):
            raise ValueError("existing_ev_demand_requires_reconciliation")
        adapter = IndependentDailyTariffAdapter()
        covered = adapter.published_horizon_end(
            snapshot, maximum_horizon_end=min(deadline, snapshot.horizon_end or deadline))
        if covered < start + duration:
            raise ValueError("known_horizon_has_insufficient_capacity")
        tariffs = adapter.build(snapshot, horizon_end=covered)
        # A battery projection is optional evidence of PV remaining AFTER house
        # and battery demand. Never rebuild a route or use battery discharge as PV.
        surplus: list[tuple[datetime, datetime, float]] = []
        context = snapshot.daily_charge_context
        pv_reason = "battery_projection_unavailable_grid_prices_used"
        if (context is not None and context.status == "ready" and conversion_model is not None
                and snapshot.current_storage_states):
            plans = [p for p in context.main_plans if p.plan_id in context.active_main_plan_ids
                     and p.valid_from <= now < p.valid_until]
            if len(plans) == 1:
                try:
                    reference = IndependentDailyReferenceAdapter()
                    reasons = reference.committed_execution_invalidity_reasons(
                        snapshot=snapshot, plan=plans[0], conversion_model=conversion_model,
                        household_grid_fallback=True)
                    if not reasons:
                        projection, _ = reference.committed_plan_projection(
                            snapshot=snapshot, plan=plans[0], conversion_model=conversion_model)
                        surplus = [(i.starts_at, i.ends_at, i.pv_to_grid_wh)
                                   for i in projection.intervals]
                        pv_reason = "surplus_after_house_and_battery"
                except (ValueError, TypeError):
                    pass  # Unproven solar is never credited; grid planning remains available.
        edges = {t for i in tariffs.intervals for t in (i.starts_at, i.ends_at)}
        edges.update(t for left, right, _ in surplus for t in (left, right))
        if execution_not_before is not None:
            not_before = execution_not_before()
            if not_before.utcoffset() is None:
                raise ValueError("execution_not_before_requires_offset")
            start = max(start, not_before)
        if start + duration > covered:
            raise ValueError("no_future_ev_start_after_comparison")
        candidates = _placement_starts(start, covered - duration, duration, tuple(edges))
        comparisons: list[dict[str, Any]] = []
        for at in candidates:
            end = at + duration
            borders = sorted({at, end, *(t for t in edges if at < t < end)})
            cost = solar = 0.0
            for left, right in zip(borders, borders[1:], strict=False):
                amount = power * (right - left).total_seconds() / 3600
                tariff = next(i for i in tariffs.intervals
                              if i.starts_at <= left and right <= i.ends_at)
                free_pv = sum(wh * (right - left) / (b - a)
                              for a, b, wh in surplus if a <= left and right <= b)
                used = min(amount, max(0.0, free_pv))
                # Solar costs the foregone export value, not zero euros.
                cost += ((amount - used) * tariff.import_eur_per_kwh
                         + used * tariff.export_eur_per_kwh) / 1000
                solar += used
            comparisons.append({"starts_at": at.isoformat(), "ends_at": end.isoformat(),
                                "ev_cost_eur": cost, "pv_energy_wh": solar})
        best = min(comparisons, key=lambda c: (c["ev_cost_eur"], c["starts_at"]))
        provisional = covered < deadline
        result.update(
            status="provisional" if provisional else "ready",
            reason="best_ev_grid_and_surplus_pv_window",
            provisional=provisional,
            provisional_reasons=["prices_missing_before_requested_deadline"] if provisional else [],
            price_coverage_until=covered.isoformat(), assessed_horizon_until=covered.isoformat(),
            scheduled_energy_wh=energy, estimated_ev_cost_eur=round(best["ev_cost_eur"], 6),
            estimated_pv_energy_wh=round(best["pv_energy_wh"], 3), pv_assessment=pv_reason,
            candidate_count=len(candidates), rejected_candidate_count=0, search_truncated=False,
            candidate_comparisons=comparisons, earliest_executable_start=start.isoformat(),
            slots=[{"starts_at": best["starts_at"], "ends_at": best["ends_at"],
                    "energy_wh": energy}],
        )
    except (ValueError, TypeError, OverflowError) as error:
        result.update(status="blocked", reason=str(error))
    return result
