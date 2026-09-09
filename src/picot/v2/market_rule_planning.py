"""Compose market user-rule alternatives through the existing physical models.

This module supplies candidates; Evaluation and PlanBuilder retain authority.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256

from picot.domain.candidate import (
    Candidate,
    CandidateExclusion,
    CandidateExclusionKind,
    CandidateFamily,
    CandidateSet,
)
from picot.domain.daily_reference_charge_window import (
    DailyMainChargeWindow,
)
from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_simulation import DailyPlanningProjection
from picot.domain.energy_path import (
    EnergyPath,
    PathSegment,
    ProjectedEnergyState,
    RetainedExecutionOrigin,
)
from picot.domain.evaluation import (
    CandidateOutcome,
    CandidateOutcomeSet,
    CandidateValidity,
    ComparisonDirection,
    ObjectiveOutcome,
)
from picot.domain.execution_plan import ExecutionPlan
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.domain.market_user_rule import MarketPricePart, MarketPriceWindow, MarketSpreadEvidence
from picot.domain.objectives import ObjectiveKind, ObjectiveWeight, WeightedObjective
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.independent_daily_charge_window_discoverer import (
    IndependentDailyChargeWindowDiscoverer,
)
from picot.planner.market_export_windows import ExportCapacityPart, export_windows
from picot.planner.market_price_windows import market_price_alternatives
from picot.planner.market_route_admission import (
    MarketAdmission,
    MarketRecoverySegment,
    assess_market_route,
)
from picot.planner.mep_candidate_outcomes import (
    MainChargeComparablePortfolio,
    _main_charge_energy_path,
    _strategy,
    produce_main_charge_portfolio,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.daily_charge_assignment import DailyChargeAssignment, DailyMainShortfallTrigger
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter


def identity(kind: str, value: str) -> str:
    return kind + ":" + sha256(value.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class MarketCandidateEvidence:
    candidate_id: str
    spread: MarketSpreadEvidence
    admission: MarketAdmission
    segment_energy: tuple[tuple[str, float], ...]
    charge_window: DailyMainChargeWindow | None = None
    charge_trigger: DailyMainShortfallTrigger | None = None
    expected_battery_draw_wh: float | None = None


@dataclass(frozen=True, slots=True)
class MarketRulePortfolio:
    comparable: MainChargeComparablePortfolio
    evidence: tuple[MarketCandidateEvidence, ...]
    reasons: tuple[str, ...]


def market_rule_portfolio(
    *,
    snapshot: PlanningInputSnapshot,
    plan: ExecutionPlan,
    assignment: MarketDailyAssignment,
    conversion: StorageConversionModel,
    opportunity_ids: tuple[str, ...],
    planning_checkpoint: Callable[[], None] | None = None,
    wear_eur_per_export_kwh: float = 0.0,
    saldering_energy_tax_credit_enabled: bool = True,
) -> MarketRulePortfolio:
    context = snapshot.daily_charge_context
    if context is None or context.status != "ready" or len(snapshot.current_storage_states) != 1:
        raise ValueError("market requires ready single-storage planning input")
    storage = snapshot.current_storage_states[0]
    limits = next(
        i
        for i in snapshot.storage_physical_limits
        if i.execution_scope_id == plan.execution_scope_id
    )
    if snapshot.capability_snapshot_set is None:
        raise ValueError("market_capability_evidence_missing")
    capability = next(
        c
        for c in snapshot.capability_snapshot_set.capabilities
        if c.capability_id == storage.capability_id
    )
    if ExecutionPrimitive.DISCHARGE_AT_POWER not in capability.supported_primitives:
        raise ValueError("market_export_capability_unavailable")
    tariffs_adapter = IndependentDailyTariffAdapter()
    prices = tariffs_adapter.build(
        snapshot,
        horizon_start=assignment.starts_at,
        horizon_end=assignment.ends_at,
        saldering_energy_tax_credit_enabled=saldering_energy_tax_credit_enabled,
    )
    seeds = market_price_alternatives(
        rule=assignment.rule,
        tariffs=prices,
        delivery_start=assignment.starts_at,
        delivery_end=assignment.ends_at,
        earliest_export=snapshot.captured_at,
        usable_capacity_wh=assignment.usable_capacity_wh,
        charge_power_w=limits.maximum_charge_input_power_w,
        discharge_power_w=limits.maximum_discharge_output_power_w,
        conversion=conversion,
    )
    if not seeds:
        raise ValueError("market_volume_does_not_fit_published_day")
    adapter = IndependentDailyReferenceAdapter()
    owner = next(
        a
        for a in context.assignments
        if a.route_plan_id is not None and a.execution_scope_id == plan.execution_scope_id
    )
    boundaries = tuple(t for p in plan.segments for t in (p.starts_at, p.ends_at))
    data = adapter.build_inputs(
        snapshot,
        horizon_end=plan.valid_until,
        maximum_duration=timedelta(hours=36),
        extra_boundaries=boundaries,
    )
    base_schedule, _ = adapter._retained_main_schedule(
        snapshot=snapshot,
        assignment=owner,
        inputs=data,
        supplied=None,
    )
    assert base_schedule is not None
    base = adapter._bridge_projection(snapshot, data, base_schedule, conversion)
    capacities = []
    for baseline_interval in base.intervals:
        left, right = (
            max(baseline_interval.starts_at, assignment.starts_at),
            min(baseline_interval.ends_at, assignment.ends_at),
        )
        if left >= right:
            continue
        source = next(s for s in plan.segments if s.starts_at <= left < right <= s.ends_at)
        if (
            source.main_assignment_id
            or source.purpose.startswith("supplemental:")
            or (
                source.primitive
                in {ExecutionPrimitive.CHARGE_AT_POWER, ExecutionPrimitive.DISCHARGE_AT_POWER}
            )
        ):
            continue
        hours = (baseline_interval.ends_at - baseline_interval.starts_at).total_seconds() / 3600
        house_w = (
            max(0, baseline_interval.household_demand_wh - baseline_interval.pv_to_household_wh)
            / hours
        )
        capacities.append(
            ExportCapacityPart(
                left, right, max(0, limits.maximum_discharge_output_power_w - house_w)
            )
        )
    windows = export_windows(
        tuple(capacities), assignment.battery_energy_wh * conversion.discharge_efficiency
    )
    strategy = replace(
        _strategy(snapshot),
        objectives=(WeightedObjective(ObjectiveKind.FINANCIAL_RESULT, ObjectiveWeight(100)),),
    )
    candidates, paths, outcomes, evidence, reasons = [], [], [], [], []
    recovery = tuple(
        MarketRecoverySegment(a.assignment_id, s.starts_at, s.ends_at, storage.usable_capacity_wh)
        for a in context.assignments
        if a.completed_at is None
        for s in a.main_segments
        if s.ends_at > snapshot.captured_at
    ) + tuple(
        MarketRecoverySegment(
            g.assignment_id, g.starts_at, g.ends_at, g.target_soc * storage.usable_capacity_wh
        )
        for g in context.supplemental_assignments
        if g.completed_at is None
    )

    def goals_reached(
        projection: DailyPlanningProjection, charge_window: DailyMainChargeWindow | None
    ) -> bool:
        goals = [
            (
                tuple(
                    (seg.starts_at, seg.ends_at)
                    for seg in (
                        charge_window.main_segments
                        if charge_window is not None
                        and a.assignment_id == charge_window.assignment_id
                        else a.main_segments
                    )
                ),
                storage.usable_capacity_wh,
            )
            for a in context.assignments
            if a.completed_at is None
            and any(seg.ends_at > snapshot.captured_at for seg in a.main_segments)
        ] + [
            (((g.starts_at, g.ends_at),), g.target_soc * storage.usable_capacity_wh)
            for g in context.supplemental_assignments
            if g.completed_at is None and g.ends_at > snapshot.captured_at
        ]
        return not any(
            not any(
                any(start <= at <= end for start, end in goal_windows) and energy + 1e-6 >= target
                for interval in projection.intervals
                for at, energy in (
                    (interval.starts_at, interval.storage_energy_at_start_wh),
                    (interval.ends_at, interval.storage_energy_at_end_wh),
                )
            )
            for goal_windows, target in goals
        )

    def window_price(window: tuple[ExportCapacityPart, ...]) -> float:
        cost, energy = 0.0, 0.0
        for part in window:
            for price in prices.intervals:
                left, right = max(part.starts_at, price.starts_at), min(part.ends_at, price.ends_at)
                if left >= right:
                    continue
                amount = part.export_power_w * (right - left).total_seconds() / 3600
                rate = price.cross_interval_export_eur_per_kwh
                cost += amount * (rate if rate is not None else price.export_eur_per_kwh)
                energy += amount
        return cost / energy

    priced = sorted(((window_price(w), w) for w in windows), key=lambda item: -item[0])
    admitted_price: float | None = None
    dominated = False
    for price_bound, window in priced:
        if planning_checkpoint is not None:
            planning_checkpoint()
        # Candidate dominance, not a new winner selector: a strictly lower
        # export price cannot beat an already admitted candidate under this
        # explicit one-objective user rule. All arithmetic ties still reach
        # the existing Evaluation Engine and its declared tie-breakers.
        if (
            not assignment.rule.recovery_required
            and admitted_price is not None
            and price_bound < admitted_price - 1e-12
        ):
            dominated = True
            continue
        first, last = window[0].starts_at, window[-1].ends_at
        candidate_id = identity(
            "market-candidate", f"{snapshot.snapshot_id}|{assignment.assignment_id}|{first}|{last}"
        )
        refined = adapter.build_inputs(
            snapshot,
            horizon_end=plan.valid_until,
            maximum_duration=timedelta(hours=36),
            extra_boundaries=boundaries + (first, last),
        )
        schedule, _ = adapter._retained_main_schedule(
            snapshot=snapshot,
            assignment=owner,
            inputs=refined,
            supplied=None,
        )
        assert schedule is not None
        baseline = adapter._bridge_projection(snapshot, refined, schedule, conversion)
        parts, price_parts = [], []
        for i in schedule.intervals:
            allocation = next(
                (p for p in window if p.starts_at <= i.starts_at < i.ends_at <= p.ends_at), None
            )
            if allocation is None:
                parts.append(i)
                continue
            amount = allocation.export_power_w * (i.ends_at - i.starts_at).total_seconds() / 3600
            parts.append(
                replace(
                    i, intent=DailyStorageIntent.STORAGE_EXPORT, storage_export_target_wh=amount
                )
            )
            price = next(
                p for p in prices.intervals if p.starts_at <= i.starts_at < i.ends_at <= p.ends_at
            )
            price_parts.append(
                MarketPricePart(
                    i.starts_at,
                    i.ends_at,
                    amount,
                    price.cross_interval_export_eur_per_kwh
                    if price.cross_interval_export_eur_per_kwh is not None
                    else price.export_eur_per_kwh,
                    price.evidence_ids,
                )
            )
        proposed_schedule = replace(schedule, schedule_id=candidate_id, intervals=tuple(parts))
        proposed = adapter._bridge_projection(snapshot, refined, proposed_schedule, conversion)
        spread = replace(seeds[0], export_window=MarketPriceWindow(tuple(price_parts), False))
        if not spread.meets_spread:
            reasons.append("user_spread_not_met")
            continue
        charge_window = None
        charge_trigger = None

        def main_peak(
            a: DailyChargeAssignment, projection: DailyPlanningProjection = proposed
        ) -> float:
            return max(
                (
                    energy
                    for interval in projection.intervals
                    for at, energy in (
                        (interval.starts_at, interval.storage_energy_at_start_wh),
                        (interval.ends_at, interval.storage_energy_at_end_wh),
                    )
                    if any(
                        segment.starts_at <= at <= segment.ends_at for segment in a.main_segments
                    )
                ),
                default=0,
            )

        short = next(
            (
                a
                for a in sorted(context.assignments, key=lambda a: a.delivery_date)
                if a.completed_at is None
                and a.route_plan_id is not None
                and a.ends_at > snapshot.captured_at
                and main_peak(a) + 1e-6 < storage.usable_capacity_wh
            ),
            None,
        )
        if short is not None:
            assert short.route_plan_id is not None
            charge_trigger = DailyMainShortfallTrigger(
                short.assignment_id,
                short.route_plan_id,
                short.revision,
                plan.plan_id,
                snapshot.snapshot_id,
                snapshot.captured_at,
                main_peak(short),
                storage.usable_capacity_wh,
                assignment.assignment_id,
            )
            revision_schedule = replace(
                proposed_schedule,
                intervals=tuple(
                    replace(
                        interval,
                        intent=DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
                        storage_export_target_wh=0,
                    )
                    if any(
                        seg.starts_at <= interval.starts_at < interval.ends_at <= seg.ends_at
                        for seg in short.main_segments
                    )
                    else interval
                    for interval in proposed_schedule.intervals
                ),
            )
            protected = tuple(
                (seg.starts_at, seg.ends_at)
                for a in context.assignments
                if a.assignment_id != short.assignment_id
                for seg in a.main_segments
            )
            protected += tuple((g.starts_at, g.ends_at) for g in context.supplemental_assignments)
            revised = IndependentDailyChargeWindowDiscoverer().discover_main_charge(
                snapshot_id=snapshot.snapshot_id,
                assignment=short,
                household=refined.household,
                pv_scenarios=refined.pv_scenarios,
                storage_state=refined.storage,
                conversion_model=conversion,
                minimum_storage_energy_wh=refined.minimum_storage_energy_wh,
                target_storage_energy_wh=refined.target_storage_energy_wh,
                maximum_charge_input_power_w=refined.maximum_charge_input_power_w,
                maximum_discharge_output_power_w=refined.maximum_discharge_output_power_w,
                retained_schedule=revision_schedule,
                optimisation_trigger=charge_trigger,
                protected_intervals=protected,
            )
            _, retained_main = adapter._retained_main_schedule(
                snapshot=snapshot,
                assignment=short,
                inputs=refined,
                supplied=None,
                revising_assignment_id=short.assignment_id,
            )
            revised = replace(
                revised,
                windows=tuple(
                    replace(
                        w,
                        retained_main_segments=retained_main,
                        supplemental_assignments=tuple(
                            g for g in context.supplemental_assignments if g.completed_at is None
                        ),
                    )
                    for w in revised.windows
                    if goals_reached(w.projection, w)
                ),
            )
            if not revised.windows:
                reasons.append("market_and_charge_physically_unreachable")
                continue
            charge_prices = tariffs_adapter.build(
                snapshot,
                horizon_end=plan.valid_until,
                saldering_energy_tax_credit_enabled=saldering_energy_tax_credit_enabled,
            )
            charge_portfolio = produce_main_charge_portfolio(
                snapshot=snapshot,
                windows=revised,
                tariffs=charge_prices,
                opportunity_ids=opportunity_ids,
            )
            charge_result = EvaluationEngine().evaluate(
                charge_portfolio.candidate_set,
                charge_portfolio.strategy,
                charge_portfolio.outcome_set,
                created_at=snapshot.captured_at,
            )
            if charge_result.winning_energy_path is None:
                reasons.append("market_charge_optimisation_has_no_winner")
                continue
            charge_window = next(
                row.window
                for row in charge_portfolio.sources
                if row.candidate_id == charge_result.record.winning_candidate_id
            )
            proposed = charge_window.projection
            proposed_schedule = charge_window.schedule
        actual_tariffs = (
            tariffs_adapter.build(
                snapshot,
                horizon_end=plan.valid_until,
                saldering_energy_tax_credit_enabled=saldering_energy_tax_credit_enabled,
            )
            if assignment.rule.recovery_required
            else None
        )
        recovery_for_candidate = (
            recovery
            if charge_window is None
            else tuple(r for r in recovery if r.assignment_id != charge_window.assignment_id)
            + tuple(
                MarketRecoverySegment(
                    charge_window.assignment_id,
                    seg.starts_at,
                    seg.ends_at,
                    storage.usable_capacity_wh,
                )
                for seg in charge_window.main_segments
            )
        )
        admission = assess_market_route(
            assignment=assignment,
            spread=spread,
            baseline=baseline,
            proposed=proposed,
            minimum_storage_energy_wh=refined.minimum_storage_energy_wh,
            recovery_segments=recovery_for_candidate,
            tariffs=actual_tariffs,
            wear_eur_per_export_kwh=wear_eur_per_export_kwh,
        )
        if admission.status != "admissible":
            reasons.append(admission.reason)
            continue
        if not goals_reached(proposed, charge_window):
            reasons.append("market_and_retained_charge_goals_unreachable")
            continue
        segments: list[PathSegment] = []
        segment_energy: list[tuple[str, float]] = []
        for old in plan.segments:
            cuts = sorted(
                {old.starts_at, old.ends_at}
                | {
                    t
                    for p in price_parts
                    for t in (p.starts_at, p.ends_at)
                    if old.starts_at < t < old.ends_at
                }
            )
            for left, right in zip(cuts, cuts[1:], strict=False):
                price_part = next(
                    (p for p in price_parts if p.starts_at == left and p.ends_at == right), None
                )
                is_trade = price_part is not None
                origin = old.retained_execution_origin or (
                    RetainedExecutionOrigin(plan.plan_id, old.segment_id)
                    if old.main_assignment_id
                    else None
                )
                source_id = identity("market-path-segment", f"{candidate_id}|{left}|{right}")
                segments.append(
                    PathSegment(
                        source_id,
                        len(segments) + 1,
                        plan.execution_scope_id,
                        left,
                        right,
                        ExecutionPrimitive.DISCHARGE_AT_POWER if is_trade else old.primitive,
                        old.capability_id,
                        assignment.assignment_id if is_trade else old.purpose,
                        (assignment.assignment_id, proposed_schedule.schedule_id),
                        requested_power_w=limits.maximum_discharge_output_power_w
                        if is_trade
                        else old.requested_power_w,
                        soc_constraint=old.soc_constraint,
                        energy_profile_id=old.energy_profile_id,
                        charge_source_policy=None if is_trade else old.charge_source_policy,
                        main_assignment_id=old.main_assignment_id,
                        retained_execution_origin=origin,
                    )
                )
                if price_part is not None:
                    segment_energy.append((source_id, price_part.grid_energy_wh))
        confidence = min(i.confidence for i in proposed.intervals)
        states = (
            ProjectedEnergyState(
                at=proposed.intervals[0].starts_at,
                confidence=confidence,
                storage_energy_wh=storage.current_stored_energy_wh,
                battery_soc=storage.current_soc,
            ),
        ) + tuple(
            ProjectedEnergyState(
                at=i.ends_at,
                confidence=i.confidence,
                storage_energy_wh=i.storage_energy_at_end_wh,
                battery_soc=min(1, i.storage_energy_at_end_wh / storage.usable_capacity_wh),
            )
            for i in proposed.intervals
        )
        path = EnergyPath(
            identity("market-path", candidate_id),
            snapshot.snapshot_id,
            CandidateFamily.MARKET_ROUTE,
            plan.valid_from,
            plan.valid_until,
            tuple(segments),
            states,
            opportunity_ids,
            (assignment.rule.rule_id,),
            (storage.capability_id,),
            strategy.strategy_version,
            plan.mapping_version,
            ("user-rule export; import reference is fictitious",),
            confidence,
        )
        if charge_window is not None:
            path = _main_charge_energy_path(
                snapshot=snapshot,
                window=charge_window,
                candidate_id=candidate_id,
                family=CandidateFamily.MARKET_ROUTE,
                confidence=confidence,
                opportunity_ids=opportunity_ids,
                strategy_version=strategy.strategy_version,
            )
            path = replace(
                path,
                segments=tuple(
                    replace(segment, purpose=assignment.assignment_id)
                    if segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER
                    and first <= segment.starts_at < segment.ends_at <= last
                    else segment
                    for segment in path.segments
                ),
            )
            segment_energy = [
                (
                    segment.segment_id,
                    sum(
                        part.grid_energy_wh
                        * (
                            min(part.ends_at, segment.ends_at)
                            - max(part.starts_at, segment.starts_at)
                        ).total_seconds()
                        / (part.ends_at - part.starts_at).total_seconds()
                        for part in price_parts
                        if part.starts_at < segment.ends_at and segment.starts_at < part.ends_at
                    ),
                )
                for segment in path.segments
                if segment.purpose == assignment.assignment_id
            ]
        candidates.append(
            Candidate(
                candidate_id,
                snapshot.snapshot_id,
                path.family,
                path.path_id,
                path.opportunity_ids,
                path.constraint_ids,
                path.strategy_version,
                path.capability_ids,
                path.assumptions,
                confidence,
            )
        )
        paths.append(path)
        outcomes.append(
            CandidateOutcome(
                candidate_id,
                (
                    ObjectiveOutcome(
                        ObjectiveKind.FINANCIAL_RESULT,
                        admission.incremental_net_profit_eur
                        if assignment.rule.recovery_required
                        and admission.incremental_net_profit_eur is not None
                        else spread.export_window.average_eur_per_kwh,
                        ComparisonDirection.HIGHER_IS_BETTER,
                        "EUR" if assignment.rule.recovery_required else "EUR/export-kWh",
                        confidence,
                        (assignment.assignment_id,),
                    ),
                ),
                confidence,
                None,
                len(segments),
                max(0, len(segments) - 1),
                "market-segments:v1",
                CandidateValidity.VALID,
                evidence_ids=(assignment.assignment_id,),
            )
        )
        traded = tuple(i for i in proposed.intervals if first <= i.starts_at < i.ends_at <= last)
        battery_draw = traded[0].storage_energy_at_start_wh - traded[-1].storage_energy_at_end_wh
        evidence.append(
            MarketCandidateEvidence(
                candidate_id,
                spread,
                admission,
                tuple(segment_energy),
                charge_window,
                charge_trigger,
                battery_draw,
            )
        )
        admitted_price = max(
            admitted_price if admitted_price is not None else price_bound, price_bound
        )
    candidate_set = CandidateSet(
        snapshot.snapshot_id,
        strategy.strategy_version,
        tuple(candidates),
        tuple(paths),
        (
            CandidateExclusion(
                CandidateFamily.MARKET_ROUTE,
                CandidateExclusionKind.DOMINATED,
                "lower weighted export price than an admissible same-volume candidate",
                (assignment.assignment_id,),
            ),
        )
        if dominated
        else (),
    )
    outcome_set = CandidateOutcomeSet(
        snapshot.snapshot_id,
        strategy.strategy_version,
        EvaluationEngine.candidate_set_reference(candidate_set),
        tuple(outcomes),
    )
    return MarketRulePortfolio(
        MainChargeComparablePortfolio(candidate_set, outcome_set, strategy, ()),
        tuple(evidence),
        tuple(sorted(set(reasons))),
    )
