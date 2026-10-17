"""Read-only EV placement comparison on the retained canonical battery route."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

METHOD = "ev-retained-route-advice:v1"


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


def _overlay(snapshot: PlanningInputSnapshot, start: datetime, end: datetime,
             power: float, boundary: datetime) -> PlanningInputSnapshot:
    """Split demand exactly; this advice never delegates extra battery support."""
    forecast = snapshot.household_load_forecast
    if forecast is None:
        raise ValueError("household_forecast_missing")
    intervals = []
    for item in forecast.intervals:
        edges = sorted({item.starts_at, item.ends_at, *(t for t in (start, end, boundary)
                       if item.starts_at < t < item.ends_at)})
        for n, (left, right) in enumerate(zip(edges, edges[1:], strict=False)):
            fraction = (right - left) / (item.ends_at - item.starts_at)
            extra = power * (right - left).total_seconds() / 3600 if start <= left < end else 0
            intervals.append(replace(
                item, interval_id=f"{item.interval_id}:ev:{n}", starts_at=left, ends_at=right,
                expected_energy_wh=item.expected_energy_wh * fraction + extra,
                battery_excluded_energy_wh=item.battery_excluded_energy_wh * fraction + extra,
            ))
    return replace(snapshot, household_load_forecast=replace(forecast, intervals=tuple(intervals)))


def advise(snapshot: PlanningInputSnapshot, request: dict[str, Any],
           conversion_model: StorageConversionModel) -> dict[str, Any]:
    """Compare bounded contiguous placements; no execution or commitment writes.

    Every placement retains the battery route and may not lower its stored energy
    at any original projection boundary. Unknown future tariff hours are excluded.
    """
    result: dict[str, Any] = {
        "contract": "energy-device-charging-advice:v1", "session_id": request.get("session_id"),
        "request_revision": request.get("request_revision"),
        "generated_at": snapshot.captured_at.isoformat(), "snapshot_id": snapshot.snapshot_id,
        "run_id": snapshot.run_id, "method_version": METHOD, "status": "blocked",
        "slots": [], "scheduled_energy_wh": 0, "advisory_only": True,
        "selection_scope": "bounded_contiguous_windows_on_retained_battery_route",
        "storage_support_allowed": False,
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
        evidence = _time(request.get("evidence_at"))
        now = snapshot.captured_at.astimezone(UTC)
        if (not available < deadline <= min(available, now) + timedelta(days=7)
                or evidence > now):
            raise ValueError("invalid_request_window")
        energy = _number(request.get("remaining_energy_wh"), 0, 88320)
        power = _number(request.get("fixed_power_w"), 100, 3680)
        result.update(required_energy_wh=energy, ready_by=deadline.isoformat())
        start = max(now, available)
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
        plans = tuple(p for p in context.main_plans if p.plan_id in context.active_main_plan_ids
                      and p.valid_from <= now < p.valid_until) if context else ()
        if context is None or context.status != "ready" or len(plans) != 1:
            raise ValueError("retained_battery_plan_unavailable")
        plan = plans[0]
        adapter = IndependentDailyReferenceAdapter()
        if adapter.committed_execution_invalidity_reasons(
                snapshot=snapshot, plan=plan, conversion_model=conversion_model):
            raise ValueError("retained_battery_plan_requires_repair")
        tariff_adapter = IndependentDailyTariffAdapter()
        published = tariff_adapter.published_horizon_end(
            snapshot, maximum_horizon_end=snapshot.horizon_end or plan.valid_until)
        covered = min(published, deadline, plan.valid_until)
        result.update(price_coverage_until=published.isoformat(),
                      published_price_coverage_until=published.isoformat(),
                      assessed_horizon_until=covered.isoformat(),
                      retained_plan_id=plan.plan_id, provisional=covered < deadline)
        latest = covered - duration
        if latest < start:
            raise ValueError("known_horizon_has_insufficient_capacity")
        # Include tariff edges and exact latest finish, without inventing prices.
        starts = {start, latest}
        starts.update(p.starts_at.astimezone(UTC) for p in snapshot.price_points
                      if start <= p.starts_at <= latest)
        ordered = sorted(starts)
        truncated = len(ordered) > 200
        if truncated:
            ordered = [ordered[round(n * (len(ordered) - 1) / 199)] for n in range(200)]
        baseline_snapshot = _overlay(snapshot, start, start, 0, covered)
        baseline, _ = adapter.committed_plan_projection(
            snapshot=baseline_snapshot, plan=plan, conversion_model=conversion_model,
            extra_boundaries=(start, covered))
        protected = {i.ends_at: i.storage_energy_at_end_wh for i in baseline.intervals}
        tariffs = tariff_adapter.build(baseline_snapshot, horizon_end=covered)
        settlement = IndependentDailyFinancialSettlement()

        def cash(projection: Any) -> float:
            # Settle only published hours, while physical checks retain the full plan.
            clipped = replace(projection, intervals=tuple(i for i in projection.intervals
                              if i.ends_at <= covered), basis_timeline=replace(
                                  projection.basis_timeline, horizon_end=covered,
                                  intervals=tuple(i for i in projection.basis_timeline.intervals
                                                  if i.ends_at <= covered)))
            settled = settlement.settle_planning_basis(projection=clipped, tariffs=tariffs)
            return settled.cash_result_eur

        baseline_cash = cash(baseline)
        candidates, paths, outcomes = [], [], []
        costs: dict[str, tuple[datetime, float]] = {}
        rejected = 0
        for index, placement in enumerate(ordered):
            changed = _overlay(snapshot, placement, placement + duration, power, covered)
            if adapter.committed_execution_invalidity_reasons(
                    snapshot=changed, plan=plan, conversion_model=conversion_model):
                rejected += 1
                continue
            projection, _ = adapter.committed_plan_projection(
                snapshot=changed, plan=plan, conversion_model=conversion_model,
                extra_boundaries=(start, placement, placement + duration, covered))
            if any(i.storage_energy_at_end_wh + 1e-6 < protected[i.ends_at]
                   for i in projection.intervals if i.ends_at in protected):
                rejected += 1
                continue
            value = cash(projection)
            confidence = min(i.confidence for i in projection.intervals)
            candidate_id, path_id = f"ev:{index:03d}", f"ev-path:{index:03d}"
            assumptions = (METHOD, "battery_support_excluded", plan.plan_id)
            family = CandidateFamily.COST_FIRST
            paths.append(EnergyPath(
                path_id, snapshot.snapshot_id, family, now, plan.valid_until, (),
                tuple(ProjectedEnergyState(i.ends_at, i.confidence,
                      storage_energy_wh=i.storage_energy_at_end_wh) for i in projection.intervals),
                (), (), (), 1, 1, assumptions, confidence,
            ))
            candidates.append(Candidate(candidate_id, snapshot.snapshot_id, family, path_id,
                                        (), (), 1, (), assumptions, confidence))
            outcomes.append(CandidateOutcome(
                candidate_id, (ObjectiveOutcome(ObjectiveKind.FINANCIAL_RESULT, value,
                ComparisonDirection.HIGHER_IS_BETTER, "EUR", confidence,
                (snapshot.snapshot_id,)),),
                confidence, None, 1, 2, METHOD, CandidateValidity.VALID,
            ))
            costs[candidate_id] = (placement, baseline_cash - value)
        result.update(candidate_count=len(ordered), rejected_candidate_count=rejected,
                      search_truncated=truncated, provisional=covered < deadline or truncated)
        if not candidates:
            raise ValueError("no_placement_preserves_battery_commitments")
        candidate_set = CandidateSet(snapshot.snapshot_id, 1, tuple(candidates), tuple(paths), ())
        engine = EvaluationEngine()
        strategy = PlannerStrategy(1, 1, METHOD, OptimisationProfile.CONSERVATIVE,
                    (WeightedObjective(ObjectiveKind.FINANCIAL_RESULT, ObjectiveWeight(1000)),))
        outcome_set = CandidateOutcomeSet(snapshot.snapshot_id, 1,
                         engine.candidate_set_reference(candidate_set), tuple(outcomes))
        evaluation = engine.evaluate(candidate_set, strategy, outcome_set, created_at=now)
        winner = evaluation.winning_candidate
        if winner is None:
            raise ValueError("evaluation_has_no_winner")
        chosen, cost = costs[winner.candidate_id]
        result.update(status="provisional" if covered < deadline or truncated else "ready",
                      reason="best_evaluated_contiguous_window", scheduled_energy_wh=energy,
                      estimated_incremental_cost_eur=round(cost, 6),
                      battery_checkpoints_preserved=True,
                      winning_candidate_id=winner.candidate_id,
                      slots=[{"starts_at": chosen.isoformat(),
                              "ends_at": (chosen + duration).isoformat(), "energy_wh": energy}])
    except (ValueError, TypeError, OverflowError) as error:
        result.update(status="blocked", reason=str(error))
    return result
