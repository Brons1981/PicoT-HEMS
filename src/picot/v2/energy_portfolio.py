"""Assess up to five additional or replacement profiles without changing the route.

HC owns comfort equivalence and non-electric cost estimates. HEMS sees only
opaque plan IDs, interval energy and cost. No device data enters MEP.
"""

import hashlib
import json
import math
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.load_replacement import LoadReplacementBasis, replace_profile
from picot.v2.portfolio_recharge import discover as discover_recharge

REQUEST_ENTITY = "sensor.picot_hc_energy_proposals"
RESPONSE_ENTITY = "sensor.picot_hc_energy_assessment"


def fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def instant(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid_timestamp")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.utcoffset() is None:
        raise ValueError("timezone_required")
    return moment.astimezone(UTC)


def _number(value: Any, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("invalid_number")
    return float(value)


def _validate(snapshot: PlanningInputSnapshot, request: dict[str, Any]) -> list[dict[str, Any]]:
    replacement = request.get("contract") == "hc-energy-proposals:v2"
    keys = {
        "contract",
        "request_id",
        "revision",
        "basis_snapshot_id",
        "generated_at",
        "valid_until",
        "demand_basis",
        "comfort_equivalent",
        "plans",
    }
    if replacement:
        keys.add("replacement_basis_id")
        if "modeled_source_id" in request:
            keys.add("modeled_source_id")
            if not isinstance(request["modeled_source_id"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", request["modeled_source_id"]
            ):
                raise ValueError("invalid_modeled_source_id")
        if not isinstance(request.get("replacement_basis_id"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", request["replacement_basis_id"]
        ):
            raise ValueError("invalid_replacement_basis_id")
    if set(request) != keys or request["contract"] not in (
        "hc-energy-proposals:v1",
        "hc-energy-proposals:v2",
    ):
        raise ValueError("invalid_contract")
    if not isinstance(request["request_id"], str):
        raise ValueError("invalid_request_id")
    UUID(request["request_id"])
    if type(request["revision"]) is not int or request["revision"] < 1:
        raise ValueError("invalid_revision")
    if request["basis_snapshot_id"] != snapshot.snapshot_id:
        raise ValueError("basis_snapshot_changed")
    if (
        request["demand_basis"]
        != ("replace_controlled_load" if replacement else "additional_to_forecast")
        or request["comfort_equivalent"] is not True
    ):
        raise ValueError("demand_basis_or_comfort_unconfirmed")
    generated, expires = instant(request["generated_at"]), instant(request["valid_until"])
    if not (
        0 <= (generated - snapshot.captured_at).total_seconds() <= 120
        and 0 < (expires - generated).total_seconds() <= 180
    ):
        raise ValueError("invalid_request_validity")
    plans = request["plans"]
    if not isinstance(plans, list) or not 1 <= len(plans) <= 5:
        raise ValueError("invalid_proposal_count")
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    cost_key = "non_electric_cost_eur" if replacement else "additional_non_electric_cost_eur"
    energy_key = "energy_wh" if replacement else "additional_energy_wh"
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {
            "plan_id",
            cost_key,
            "slots",
        }:
            raise ValueError("invalid_plan_fields")
        pid = plan["plan_id"]
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", pid) or pid in seen:
            raise ValueError("invalid_plan_id")
        seen.add(pid)
        cost = _number(plan[cost_key], 1000)
        if not isinstance(plan["slots"], list) or not 1 <= len(plan["slots"]) <= 12:
            raise ValueError("invalid_slot_count")
        slots: list[dict[str, Any]] = []
        previous = generated
        for slot in plan["slots"]:
            if not isinstance(slot, dict) or set(slot) != {
                "starts_at",
                "ends_at",
                energy_key,
            }:
                raise ValueError("invalid_slot_fields")
            start, end = instant(slot["starts_at"]), instant(slot["ends_at"])
            energy = _number(slot[energy_key], 50000)
            if (
                start < previous
                or not start < end
                or (end - snapshot.captured_at).total_seconds() > 49 * 3600
            ):
                raise ValueError("invalid_slot_window")
            if energy * 3600 / (end - start).total_seconds() > 20000:
                raise ValueError("invalid_slot_power")
            if replacement and slots and start != previous:
                raise ValueError("replacement_slots_must_be_contiguous")
            slots.append(dict(start=start, end=end, energy=energy))
            previous = end
        parsed.append(dict(plan_id=pid, cost=cost, slots=slots))
    if replacement and len({(p["slots"][0]["start"], p["slots"][-1]["end"]) for p in parsed}) != 1:
        raise ValueError("replacement_plans_require_same_window")
    return parsed


def _overlay(
    snapshot: PlanningInputSnapshot, slots: list[dict[str, Any]], scale: float
) -> PlanningInputSnapshot:
    forecast = snapshot.household_load_forecast
    if forecast is None:
        raise ValueError("household_forecast_missing")
    boundaries = {s[t] for s in slots for t in ("start", "end")}
    intervals = []
    for item in forecast.intervals:
        edges = sorted(
            {
                item.starts_at,
                item.ends_at,
                *(t for t in boundaries if item.starts_at < t < item.ends_at),
            }
        )
        for n, (left, right) in enumerate(zip(edges, edges[1:], strict=False)):
            fraction = (right - left) / (item.ends_at - item.starts_at)
            extra = sum(
                s["energy"] * scale * (right - left) / (s["end"] - s["start"])
                for s in slots
                if s["start"] <= left < s["end"]
            )
            intervals.append(
                replace(
                    item,
                    interval_id=f"{item.interval_id}:hc:{n}",
                    starts_at=left,
                    ends_at=right,
                    expected_energy_wh=item.expected_energy_wh * fraction + extra,
                    battery_excluded_energy_wh=item.battery_excluded_energy_wh * fraction,
                )
            )
    return replace(snapshot, household_load_forecast=replace(forecast, intervals=tuple(intervals)))


def assess(
    snapshot: PlanningInputSnapshot,
    request: dict[str, Any],
    conversion_model: StorageConversionModel,
    replacement_basis: LoadReplacementBasis | None = None,
    terminal_requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replacement = request.get("contract") == "hc-energy-proposals:v2"
    result: dict[str, Any] = dict(
        contract="hc-energy-assessment:v1",
        status="blocked",
        request_id=request.get("request_id"),
        revision=request.get("revision"),
        basis_snapshot_id=snapshot.snapshot_id,
        generated_at=snapshot.captured_at.isoformat(),
        valid_until=request.get("valid_until"),
        selected_plan_id=None,
        assessments=[],
        execution_authorized=False,
        scope="replacement_demand_on_retained_route"
        if replacement
        else "additional_demand_on_retained_route",
    )
    try:
        plans = _validate(snapshot, request)
        result["request_fingerprint"] = fingerprint(request)
        if replacement:
            result["replacement_basis_id"] = request["replacement_basis_id"]
            if (
                replacement_basis is None
                or not replacement_basis.matches(snapshot)
                or replacement_basis.basis_id != request["replacement_basis_id"]
                or replacement_basis.modeled_source_id != request.get("modeled_source_id")
            ):
                result["condition"] = dict(kind="wait_for_attributed_forecast")
                raise ValueError("matching_replacement_basis_required")
            if (
                plans[0]["slots"][0]["start"] < replacement_basis.starts_at
                or plans[0]["slots"][-1]["end"] > replacement_basis.ends_at
            ):
                result["condition"] = dict(
                    kind="replacement_window",
                    starts_at=replacement_basis.starts_at.isoformat(),
                    ends_at=replacement_basis.ends_at.isoformat(),
                )
                raise ValueError("replacement_window_not_covered")
        context = snapshot.daily_charge_context
        active = (
            [
                p
                for p in context.main_plans
                if p.plan_id in context.active_main_plan_ids
                and p.valid_from <= snapshot.captured_at < p.valid_until
            ]
            if context
            else []
        )
        if context is None or context.status != "ready" or len(active) != 1:
            raise ValueError("retained_plan_unavailable")
        retained = active[0]
        checkpoint = None
        if terminal_requirement is not None:
            checkpoint = instant(terminal_requirement["at"])
            _number(terminal_requirement["energy_wh"], 1000000)
            if not snapshot.captured_at < checkpoint <= retained.valid_until:
                raise ValueError("reserved_terminal_requirement_not_covered")
        tariff_adapter = IndependentDailyTariffAdapter()
        coverage = tariff_adapter.published_horizon_end(
            snapshot, maximum_horizon_end=retained.valid_until
        )
        result["price_coverage_until"] = coverage.isoformat()
        if coverage < retained.valid_until:
            result["condition"] = dict(
                kind="wait_for_prices", required_until=retained.valid_until.isoformat()
            )
            raise ValueError("full_horizon_prices_required")
        adapter = IndependentDailyReferenceAdapter()
        if adapter.committed_execution_invalidity_reasons(
            snapshot=snapshot, plan=retained, conversion_model=conversion_model
        ):
            raise ValueError("retained_plan_requires_repair")
        baseline, _ = adapter.committed_plan_projection(
            snapshot=snapshot, plan=retained, conversion_model=conversion_model
        )
        terminal = baseline.intervals[-1].storage_energy_at_end_wh
        tariffs = tariff_adapter.build(snapshot, horizon_end=retained.valid_until)
        settlement = IndependentDailyFinancialSettlement()
        base_cash = settlement.settle_planning_basis(
            projection=baseline, tariffs=tariffs
        ).cash_result_eur

        def evaluate(plan: dict[str, Any], scale: float) -> tuple[Any, tuple[str, ...]]:
            changed = (
                replace_profile(snapshot, replacement_basis, plan["slots"], scale)
                if replacement and replacement_basis is not None
                else _overlay(snapshot, plan["slots"], scale)
            )
            invalid = adapter.committed_execution_invalidity_reasons(
                snapshot=changed, plan=retained, conversion_model=conversion_model
            )
            projection, _ = adapter.committed_plan_projection(
                snapshot=changed,
                plan=retained,
                conversion_model=conversion_model,
                extra_boundaries=(checkpoint,) if checkpoint else (),
            )
            if projection.intervals[-1].storage_energy_at_end_wh + 1e-6 < terminal:
                invalid = (*invalid, "terminal_storage_must_be_preserved")
            if (
                checkpoint
                and terminal_requirement is not None
                and next(
                    i.storage_energy_at_end_wh
                    for i in projection.intervals
                    if i.ends_at == checkpoint
                )
                + 1e-6
                < terminal_requirement["energy_wh"]
            ):
                invalid = (*invalid, "reserved_terminal_storage_must_be_preserved")
            return projection, invalid

        for plan in plans:
            row: dict[str, Any] = dict(plan_id=plan["plan_id"], status="rejected")
            if any(s["end"] > retained.valid_until for s in plan["slots"]):
                row.update(
                    reason="outside_retained_horizon",
                    constraint=dict(kind="end_before", ends_at=retained.valid_until.isoformat()),
                )
            else:
                projection, invalid = evaluate(plan, 1)
                recharge = None
                if invalid and replacement and replacement_basis is not None and checkpoint is None:
                    changed = replace_profile(snapshot, replacement_basis, plan["slots"])
                    try:
                        recharge = discover_recharge(changed, conversion_model, retained, terminal)
                    except ValueError:
                        # An unsupported repair must not veto another feasible proposal.
                        recharge = None
                    if recharge is not None:
                        projection, invalid = recharge.projection, ()
                if invalid:
                    # A zero replacement is NOT the unchanged baseline: test it too.
                    verified = None if replacement else 0.0
                    for scale in (0.5, 0.25, 0.0) if replacement else (0.5, 0.25):
                        _, failed = evaluate(plan, scale)
                        if not failed:
                            verified = scale
                            break
                    if verified is None:
                        row.update(
                            reason="energy_profile_not_feasible",
                            violations=list(invalid)[:6],
                            constraint=dict(
                                kind="revise_replacement_profile",
                                original_plan_id=plan["plan_id"],
                                requires_hc_comfort_recheck=True,
                            ),
                        )
                        result["assessments"].append(row)
                        continue
                    row.update(
                        reason="energy_profile_not_feasible",
                        violations=list(invalid)[:6],
                        constraint=dict(
                            kind="verified_scaled_profile",
                            original_plan_id=plan["plan_id"],
                            starts_at=plan["slots"][0]["start"].isoformat(),
                            ends_at=plan["slots"][-1]["end"].isoformat(),
                            verified_profile_scale=verified,
                            verified_profile_energy_wh=round(
                                sum(s["energy"] for s in plan["slots"]) * verified, 3
                            ),
                            maximum_not_searched=True,
                            budgets_additive=False,
                            requires_hc_comfort_recheck=True,
                            demand_basis=request["demand_basis"],
                        ),
                    )
                else:
                    cash = settlement.settle_planning_basis(
                        projection=projection, tariffs=tariffs
                    ).cash_result_eur
                    electricity = base_cash - cash
                    row.update(
                        status="feasible",
                        incremental_electricity_cost_eur=round(electricity, 6),
                        additional_non_electric_cost_eur=plan["cost"],
                        total_incremental_cost_eur=round(electricity + plan["cost"], 6),
                        terminal_storage_preserved=True,
                        confidence=min(i.confidence for i in projection.intervals),
                    )
                    if replacement:
                        row["non_electric_cost_eur"] = row.pop("additional_non_electric_cost_eur")
                    if recharge is not None:
                        row.update(
                            requires_route_commitment=True,
                            additional_grid_charge_wh=round(
                                max(
                                    0,
                                    sum(i.grid_to_storage_input_wh for i in projection.intervals)
                                    - sum(i.grid_to_storage_input_wh for i in baseline.intervals),
                                ),
                                3,
                            ),
                            recharge_method=(
                                "ordinary_planner_shortfall_repair"
                                if hasattr(recharge, "main_segments")
                                else "promised_storage_reserve_acquisition"
                            ),
                        )
            result["assessments"].append(row)
        feasible = [p for p in result["assessments"] if p["status"] == "feasible"]
        if feasible:
            selected = min(feasible, key=lambda p: (p["total_incremental_cost_eur"], p["plan_id"]))
            result.update(
                status="selected",
                selected_plan_id=selected["plan_id"],
                reason="lowest_cost_on_retained_route",
            )
            if selected.get("requires_route_commitment"):
                result.update(
                    requires_route_commitment=True,
                    reason="lowest_cost_requires_committed_recharge",
                    terminal_requirement=dict(
                        at=retained.valid_until.isoformat(), energy_wh=terminal
                    ),
                )
            elif terminal_requirement is not None:
                result["terminal_requirement"] = terminal_requirement
        else:
            result.update(status="rejected", reason="new_hc_proposals_required")
        result["retained_plan_id"] = retained.plan_id
    except (ValueError, TypeError, OverflowError) as error:
        result.update(status="blocked", reason=str(error), assessments=[], selected_plan_id=None)
    return result
