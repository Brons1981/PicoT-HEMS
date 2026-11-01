"""Read-only joint EV/battery comparison through canonical route discovery."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import Any
from uuid import UUID

from picot.domain.candidate import Candidate, CandidateFamily, CandidateSet
from picot.domain.energy_path import EnergyPath, ProjectedEnergyState
from picot.domain.evaluation import (
    CandidateOutcome,
    CandidateOutcomeSet,
    CandidateValidity,
    ComparisonDirection,
    ObjectiveOutcome,
)
from picot.domain.objectives import (
    ObjectiveKind,
    ObjectiveWeight,
    OptimisationProfile,
    PlannerStrategy,
    WeightedObjective,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.independent_daily_financial_settlement import IndependentDailyFinancialSettlement
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.ev_joint_selection import JointEVSelection, rebuilt_selection
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

METHOD = "ev-joint-route-advice:v2"


def _time(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("request_time_requires_offset")
    return result.astimezone(UTC)


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid_request_number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_request_number") from error
    if not isfinite(result) or not low <= result <= high:
        raise ValueError("invalid_request_number")
    return result


def _overlay(
    snapshot: PlanningInputSnapshot,
    start: datetime,
    end: datetime,
    power: float,
    boundary: datetime,
) -> PlanningInputSnapshot:
    """Split demand exactly; this advice never delegates extra battery support."""
    forecast = snapshot.household_load_forecast
    if forecast is None:
        raise ValueError("household_forecast_missing")
    intervals = []
    for item in forecast.intervals:
        edges = sorted(
            {
                item.starts_at,
                item.ends_at,
                *(t for t in (start, end, boundary) if item.starts_at < t < item.ends_at),
            }
        )
        for n, (left, right) in enumerate(zip(edges, edges[1:], strict=False)):
            fraction = (right - left) / (item.ends_at - item.starts_at)
            extra = power * (right - left).total_seconds() / 3600 if start <= left < end else 0
            intervals.append(
                replace(
                    item,
                    interval_id=f"{item.interval_id}:ev:{n}",
                    starts_at=left,
                    ends_at=right,
                    expected_energy_wh=item.expected_energy_wh * fraction + extra,
                    battery_excluded_energy_wh=item.battery_excluded_energy_wh * fraction + extra,
                )
            )
    return replace(snapshot, household_load_forecast=replace(forecast, intervals=tuple(intervals)))


def advise(
    snapshot: PlanningInputSnapshot,
    request: dict[str, Any],
    conversion_model: StorageConversionModel,
    *,
    selections: dict[str, JointEVSelection] | None = None,
    execution_not_before: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Compare bounded contiguous placements; no execution or commitment writes.

    Daily goals remain binding; intermediate stock is free to change. Every
    compared route has the same full valuation horizon and minimum end reserve.
    Extra remaining stock receives no financial credit.
    """
    result: dict[str, Any] = {
        "contract": "energy-device-charging-advice:v1",
        "session_id": request.get("session_id"),
        "request_revision": request.get("request_revision"),
        "generated_at": snapshot.captured_at.isoformat(),
        "snapshot_id": snapshot.snapshot_id,
        "run_id": snapshot.run_id,
        "method_version": METHOD,
        "status": "blocked",
        "slots": [],
        "scheduled_energy_wh": 0,
        "advisory_only": True,
        "selection_scope": "contiguous_ev_windows_with_joint_battery_recalculation",
        "storage_support_allowed": False,
    }
    try:
        UUID(str(request.get("session_id")))
        if (
            request.get("contract") != "energy-device-charging-request:v1"
            or request.get("state") != "requested"
            or type(request.get("request_revision")) is not int
            or request["request_revision"] < 1
            or request.get("evidence_source") != "user_grid_energy_estimate"
        ):
            raise ValueError("invalid_request_contract")
        available, deadline = _time(request.get("available_from")), _time(request.get("ready_by"))
        evidence = _time(request.get("evidence_at"))
        now = snapshot.captured_at.astimezone(UTC)
        if not available < deadline <= min(available, now) + timedelta(days=7) or evidence > now:
            raise ValueError("invalid_request_window")
        energy = _number(request.get("remaining_energy_wh"), 0, 88320)
        power = _number(request.get("fixed_power_w"), 100, 3680)
        result.update(required_energy_wh=energy, ready_by=deadline.isoformat())
        # Leave time for calculation, user acceptance and the HEMS/ED handshake.
        start = max(now + timedelta(seconds=120), available)
        result["earliest_executable_start"] = start.isoformat()
        duration = timedelta(hours=energy / power)
        if start + duration > deadline or deadline <= now:
            result.update(status="infeasible", reason="deadline_capacity_insufficient")
            return result
        if energy == 0:
            result.update(status="ready", reason="no_remaining_energy")
            return result
        policy = snapshot.external_load_policy
        if policy is not None and (policy.power_w > 0 or policy.session_id is not None):
            raise ValueError("existing_ev_demand_requires_reconciliation")
        context = snapshot.daily_charge_context
        plans = (
            tuple(
                p
                for p in context.main_plans
                if p.plan_id in context.active_main_plan_ids and p.valid_from <= now < p.valid_until
            )
            if context
            else ()
        )
        if context is None or context.status != "ready" or len(plans) != 1:
            raise ValueError("retained_battery_plan_unavailable")
        plan = plans[0]
        adapter = IndependentDailyReferenceAdapter()
        if adapter.committed_execution_invalidity_reasons(
            snapshot=snapshot, plan=plan, conversion_model=conversion_model
        ):
            raise ValueError("retained_battery_plan_requires_repair")
        tariff_adapter = IndependentDailyTariffAdapter()
        published = tariff_adapter.published_horizon_end(
            snapshot, maximum_horizon_end=snapshot.horizon_end or plan.valid_until
        )
        if published < plan.valid_until:
            raise ValueError("joint_comparison_battery_horizon_prices_incomplete")
        covered = plan.valid_until
        ev_until = min(covered, deadline)
        provisional_reasons = []
        if published < deadline:
            provisional_reasons.append("prices_missing_before_requested_deadline")
        if plan.valid_until < deadline:
            provisional_reasons.append("battery_plan_ends_before_requested_deadline")
        result.update(
            price_coverage_until=published.isoformat(),
            published_price_coverage_until=published.isoformat(),
            assessed_horizon_until=covered.isoformat(),
            retained_plan_id=plan.plan_id,
            provisional=bool(provisional_reasons),
        )
        latest = ev_until - duration
        if latest < start:
            raise ValueError("known_horizon_has_insufficient_capacity")
        ordered = _placement_starts(
            start, latest, duration, tuple(p.starts_at for p in snapshot.price_points)
        )
        truncated = False  # Compatibility field: no published edge is sampled away.
        equivalent_cache: dict[str, JointEVSelection | None] | None = None
        pv = snapshot.pv_energy_timeline
        if pv is not None and all(
            all(
                v in (None, 0)
                for v in (
                    p.pv_energy_wh,
                    p.forecast_lower_energy_wh,
                    p.forecast_central_energy_wh,
                    p.forecast_upper_energy_wh,
                )
            )
            for p in pv.intervals
        ):
            # No-PV placements outside export have identical battery dynamics.
            # A common grid keeps fractional EV ends from changing discovery.
            edges = sorted({t for at in ordered for t in (at, at + duration)})
            forecast = snapshot.household_load_forecast
            assert forecast is not None
            split = []
            for item in forecast.intervals:
                borders = [
                    item.starts_at,
                    *(t for t in edges if item.starts_at < t < item.ends_at),
                    item.ends_at,
                ]
                for n, (left, right) in enumerate(zip(borders, borders[1:], strict=False)):
                    fraction = (right - left) / (item.ends_at - item.starts_at)
                    split.append(
                        replace(
                            item,
                            interval_id=f"{item.interval_id}:joint:{n}",
                            starts_at=left,
                            ends_at=right,
                            expected_energy_wh=item.expected_energy_wh * fraction,
                            battery_excluded_energy_wh=item.battery_excluded_energy_wh * fraction,
                        )
                    )
            snapshot = replace(
                snapshot, household_load_forecast=replace(forecast, intervals=tuple(split))
            )
            equivalent_cache = {}
        baseline_snapshot = _overlay(snapshot, start, start, 0, covered)
        baseline, _ = adapter.committed_plan_projection(
            snapshot=baseline_snapshot,
            plan=plan,
            conversion_model=conversion_model,
            extra_boundaries=(start, covered),
        )
        terminal_wh = baseline.intervals[-1].storage_energy_at_end_wh
        tariffs = tariff_adapter.build(baseline_snapshot, horizon_end=covered)
        settlement = IndependentDailyFinancialSettlement()

        def cash(projection: Any) -> float:
            # Full battery horizon, including cash flows after the EV finishes.
            clipped = replace(
                projection,
                intervals=tuple(i for i in projection.intervals if i.ends_at <= covered),
                basis_timeline=replace(
                    projection.basis_timeline,
                    horizon_end=covered,
                    intervals=tuple(
                        i for i in projection.basis_timeline.intervals if i.ends_at <= covered
                    ),
                ),
            )
            settled = settlement.settle_planning_basis(projection=clipped, tariffs=tariffs)
            return settled.cash_result_eur

        baseline_cash = cash(baseline)
        candidates: list[Candidate] = []
        paths: list[EnergyPath] = []
        outcomes: list[CandidateOutcome] = []
        costs: dict[str, tuple[datetime, float]] = {}
        proofs: dict[str, JointEVSelection] = {}
        comparisons: list[dict[str, Any]] = []
        retained_costs: list[tuple[datetime, float]] = []
        rejected = 0
        for index, placement in enumerate(ordered):
            changed = _overlay(snapshot, placement, placement + duration, power, covered)
            reasons = adapter.committed_execution_invalidity_reasons(
                snapshot=changed, plan=plan, conversion_model=conversion_model
            )
            projection, _ = adapter.committed_plan_projection(
                snapshot=changed,
                plan=plan,
                conversion_model=conversion_model,
                extra_boundaries=(start, placement, placement + duration, covered),
            )
            options = []
            if (
                not reasons
                and projection.intervals[-1].storage_energy_at_end_wh + 1e-6 >= terminal_wh
            ):
                retained_costs.append((placement, -cash(projection)))
                options.append(
                    (projection, JointEVSelection(changed, dict(request), plan.plan_id, plan))
                )
            rebuilt = rebuilt_selection(
                changed,
                request,
                plan,
                conversion_model,
                terminal_wh,
                equivalent_cache=equivalent_cache,
            )
            if rebuilt is not None:
                assert rebuilt.window is not None
                options.append((rebuilt.window.projection, rebuilt))
            if not options:
                rejected += 1
                comparisons.append(
                    {
                        "starts_at": placement.isoformat(),
                        "ends_at": (placement + duration).isoformat(),
                        "rejection_reasons": list(reasons)
                        or ["terminal_storage_requirement_unreachable"],
                    }
                )
                continue
            for variant, (projection, proof) in enumerate(options):
                value = cash(projection)
                candidate_id, path_id = (
                    f"ev:{index:03d}:{variant}",
                    f"ev-path:{index:03d}:{variant}",
                )
                _add_candidate(
                    snapshot,
                    now,
                    plan.valid_until,
                    projection,
                    value,
                    candidate_id,
                    path_id,
                    plan.plan_id,
                    candidates,
                    paths,
                    outcomes,
                )
                costs[candidate_id] = (placement, baseline_cash - value)
                proofs[candidate_id] = proof
                comparisons.append(
                    {
                        "candidate_id": candidate_id,
                        "starts_at": placement.isoformat(),
                        "ends_at": (placement + duration).isoformat(),
                        "total_cost_eur": -value,
                        "terminal_storage_energy_wh": projection.intervals[
                            -1
                        ].storage_energy_at_end_wh,
                        "battery_route_changed": proof.window is not None,
                    }
                )
        result.update(
            candidate_count=len(ordered),
            rejected_candidate_count=rejected,
            search_truncated=truncated,
            provisional=bool(provisional_reasons),
            provisional_reasons=provisional_reasons,
            candidate_comparisons=comparisons,
        )
        if not candidates:
            raise ValueError("no_placement_preserves_battery_commitments")
        # A long calculation must not publish an already elapsed EV start.
        # Capture this transport/admission evidence once; Evaluation still sees
        # every assessed option, with elapsed ones explicitly inadmissible.
        not_before = start if execution_not_before is None else execution_not_before()
        if not_before.utcoffset() is None:
            raise ValueError("execution_not_before_requires_offset")
        not_before = max(start, not_before)
        result["execution_not_before"] = not_before.isoformat()
        expired = {candidate_id for candidate_id, (at, _) in costs.items() if at < not_before}
        result["rejected_candidate_count"] += len({costs[key][0] for key in expired})
        outcomes = [
            replace(
                o,
                validity=CandidateValidity.INVALID,
                invalidity_reasons=("ev_start_elapsed_during_comparison",),
            )
            if o.candidate_id in expired
            else o
            for o in outcomes
        ]
        for comparison in comparisons:
            if comparison.get("candidate_id") in expired:
                comparison["rejection_reasons"] = ["ev_start_elapsed_during_comparison"]
        candidate_set = CandidateSet(snapshot.snapshot_id, 1, tuple(candidates), tuple(paths), ())
        engine = EvaluationEngine()
        strategy = PlannerStrategy(
            1,
            1,
            METHOD,
            OptimisationProfile.CONSERVATIVE,
            (WeightedObjective(ObjectiveKind.FINANCIAL_RESULT, ObjectiveWeight(1000)),),
        )
        outcome_set = CandidateOutcomeSet(
            snapshot.snapshot_id, 1, engine.candidate_set_reference(candidate_set), tuple(outcomes)
        )
        evaluation = engine.evaluate(candidate_set, strategy, outcome_set, created_at=now)
        winner = evaluation.winning_candidate
        if winner is None:
            raise ValueError(
                "no_future_ev_start_after_comparison" if expired else "evaluation_has_no_winner"
            )
        chosen, cost = costs[winner.candidate_id]
        proof = proofs[winner.candidate_id]
        selection_id = sha256(
            (
                f"{request['session_id']}:{request['request_revision']}:"
                f"{snapshot.snapshot_id}:{chosen.isoformat()}:{proof.plan.plan_id}"
            ).encode()
        ).hexdigest()
        trigger = proof.trigger
        if trigger is not None:
            trigger = replace(
                trigger, request=replace(trigger.request, request_id="joint-ev:" + selection_id)
            )
        proof = replace(
            proof,
            trigger=trigger,
            starts_at=chosen,
            ends_at=chosen + duration,
            selection_id=selection_id,
            terminal_storage_requirement_wh=terminal_wh,
        )
        total_cost = cost - baseline_cash
        result.update(
            status="provisional" if provisional_reasons else "ready",
            reason="best_evaluated_joint_window",
            scheduled_energy_wh=energy,
            estimated_incremental_cost_eur=round(cost, 6),
            total_cost_eur=round(total_cost, 6),
            comparison_horizon_until=covered.isoformat(),
            terminal_storage_requirement_wh=terminal_wh,
            terminal_storage_energy_wh=next(
                c["terminal_storage_energy_wh"]
                for c in comparisons
                if c.get("candidate_id") == winner.candidate_id
            ),
            battery_route_changed=proof.window is not None,
            selection_id=selection_id,
            joint_acceptance_required=True,
            winning_candidate_id=winner.candidate_id,
            slots=[
                {
                    "starts_at": chosen.isoformat(),
                    "ends_at": (chosen + duration).isoformat(),
                    "energy_wh": energy,
                }
            ],
        )
        future_retained_costs = [value for at, value in retained_costs if at >= not_before]
        if future_retained_costs:
            result.update(
                baseline_total_cost_eur=round(min(future_retained_costs), 6),
                savings_eur=round(min(future_retained_costs) - total_cost, 6),
            )
        if selections is not None:
            selections[selection_id] = proof
    except (ValueError, TypeError, OverflowError) as error:
        result.update(status="blocked", reason=str(error))
    return result


def _placement_starts(
    start: datetime, latest: datetime, duration: timedelta, tariff_edges: tuple[datetime, ...]
) -> list[datetime]:
    """Enumerate every start/end price edge within the published battery horizon."""
    starts = {start, latest}
    for edge in tariff_edges:
        at = edge.astimezone(UTC)
        if start <= at <= latest:
            starts.add(at)
        if start <= at - duration <= latest:
            starts.add(at - duration)
    return sorted(starts)


def _add_candidate(
    snapshot: PlanningInputSnapshot,
    now: datetime,
    until: datetime,
    projection: Any,
    value: float,
    candidate_id: str,
    path_id: str,
    retained_plan_id: str,
    candidates: list[Any],
    paths: list[Any],
    outcomes: list[Any],
) -> None:
    confidence = min(i.confidence for i in projection.intervals)
    assumptions = (METHOD, "battery_support_excluded", retained_plan_id)
    family = CandidateFamily.COST_FIRST
    paths.append(
        EnergyPath(
            path_id,
            snapshot.snapshot_id,
            family,
            now,
            until,
            (),
            tuple(
                ProjectedEnergyState(
                    i.ends_at, i.confidence, storage_energy_wh=i.storage_energy_at_end_wh
                )
                for i in projection.intervals
            ),
            (),
            (),
            (),
            1,
            1,
            assumptions,
            confidence,
        )
    )
    candidates.append(
        Candidate(
            candidate_id,
            snapshot.snapshot_id,
            family,
            path_id,
            (),
            (),
            1,
            (),
            assumptions,
            confidence,
        )
    )
    outcomes.append(
        CandidateOutcome(
            candidate_id,
            (
                ObjectiveOutcome(
                    ObjectiveKind.FINANCIAL_RESULT,
                    value,
                    ComparisonDirection.HIGHER_IS_BETTER,
                    "EUR",
                    confidence,
                    (snapshot.snapshot_id,),
                ),
            ),
            confidence,
            None,
            1,
            2,
            METHOD,
            CandidateValidity.VALID,
        )
    )
