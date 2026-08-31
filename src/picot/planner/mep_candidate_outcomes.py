"""Canonical MEP Candidate and Candidate Outcome production.

MEP produces complete alternatives; ADR-032 Evaluation alone selects a winner.
See ADR-024, ADR-031, ADR-032, ADR-037, V2ADR-055 and V2ADR-062.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from picot.architecture_ownership import architecture_ownership
from picot.domain.candidate import (
    Candidate as DomainCandidate,
)
from picot.domain.candidate import (
    CandidateFamily,
)
from picot.domain.candidate import (
    CandidateSet as DomainCandidateSet,
)
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.daily_reference_candidate import (
    DailyReferenceCandidate,
    DailyReferenceCandidateFamily,
)
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_portfolio import DailyReferenceStrategyResult
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.energy_path import EnergyPath as DomainEnergyPath
from picot.domain.energy_path import PathSegment, ProjectedEnergyState
from picot.domain.evaluation import (
    CandidateOutcome as DomainCandidateOutcome,
)
from picot.domain.evaluation import (
    CandidateOutcomeSet as DomainCandidateOutcomeSet,
)
from picot.domain.evaluation import (
    CandidateValidity,
    ComparisonDirection,
    ObjectiveOutcome,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.objectives import (
    ObjectiveKind,
    ObjectiveWeight,
    OptimisationProfile,
    PlannerStrategy,
    WeightedObjective,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.independent_daily_candidate_engine import (
    IndependentDailyCandidateEngine,
)
from picot.planner.independent_daily_reference_portfolio import (
    IndependentDailyReferencePortfolioProducer,
)
from picot.planner.market_daily_planner import (
    MarketDailyCandidatePortfolio,
    MarketRouteAssessment,
)
from picot.v2.contracts import (
    MepCandidateOutcome,
    PlanningInputSnapshot,
    ProjectedHouseholdEnergyBalance,
    ProjectedHouseholdEnergyBalanceInterval,
    StorageEnergyRequirement,
)
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.plan_commitment_store import ActivePlanCommitment, CommittedPlanSegment

ARCHITECTURE_OWNERSHIP = architecture_ownership("mep_candidate_outcomes", __name__)
METHOD_VERSION = "mep-canonical-candidate-outcomes:v2"


@dataclass(frozen=True, slots=True)
class MepCandidateSource:
    candidate_id: str
    schedule: DailyReferenceIntentSchedule
    native_candidate: DailyReferenceCandidate | None = None
    market_assessment: MarketRouteAssessment | None = None
    incumbent_commitment: ActivePlanCommitment | None = None


@dataclass(frozen=True, slots=True)
class MepComparablePortfolio:
    candidate_set: DomainCandidateSet
    outcome_set: DomainCandidateOutcomeSet
    strategy: PlannerStrategy
    sources: tuple[MepCandidateSource, ...]
    diagnostic_outcomes: tuple[MepCandidateOutcome, ...]
    incumbent_candidate_id: str | None
    projected_balance: ProjectedHouseholdEnergyBalance
    storage_requirement: StorageEnergyRequirement


@dataclass(frozen=True, slots=True)
class _CandidateRow:
    candidate_id: str
    schedule: DailyReferenceIntentSchedule
    native: DailyReferenceCandidate | None
    market: MarketRouteAssessment | None
    commitment: ActivePlanCommitment | None
    result: DailyReferenceStrategyResult | None
    opportunity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


def _id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _strategy(snapshot: PlanningInputSnapshot) -> PlannerStrategy:
    profile = snapshot.user_objective_profile
    if profile is None:
        raise ValueError("mep_user_objective_profile_missing")
    return PlannerStrategy(
        strategy_version=profile.version,
        source_profile_version=profile.version,
        mapping_version="mep-user-objective-profile:v1",
        optimisation_profile=OptimisationProfile.BALANCED,
        objectives=(
            WeightedObjective(
                ObjectiveKind.FINANCIAL_RESULT,
                ObjectiveWeight(profile.cost_optimization_weight * 10),
            ),
            WeightedObjective(
                ObjectiveKind.SELF_CONSUMPTION,
                ObjectiveWeight(profile.self_consumption_weight * 10),
            ),
            WeightedObjective(
                ObjectiveKind.RESERVE_AVAILABILITY,
                ObjectiveWeight(profile.reserve_availability_weight * 10),
            ),
        ),
    )


def _family(native: DailyReferenceCandidate | None, *, incumbent: bool) -> CandidateFamily:
    if incumbent:
        return CandidateFamily.COMMITTED
    if native is None:
        return CandidateFamily.MARKET_ROUTE
    return {
        DailyReferenceCandidateFamily.NOM_FULL_HORIZON: CandidateFamily.PV_FIRST,
        DailyReferenceCandidateFamily.NOM: CandidateFamily.PV_FIRST,
        DailyReferenceCandidateFamily.HOUSEHOLD_SUPPORT_ONLY: CandidateFamily.RESERVE_FIRST,
        DailyReferenceCandidateFamily.GRID_REQUIREMENT: CandidateFamily.COST_FIRST,
        DailyReferenceCandidateFamily.STANDBY: CandidateFamily.SEQUENTIAL,
        DailyReferenceCandidateFamily.STORAGE_EXPORT: CandidateFamily.COST_FIRST,
        DailyReferenceCandidateFamily.MIXED_SCHEDULE: CandidateFamily.PRIORITY_FIRST,
    }[native.family]


def _primitive(intent: DailyStorageIntent) -> ExecutionPrimitive:
    return {
        DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY: ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
        DailyStorageIntent.NOM: ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        DailyStorageIntent.STANDBY: ExecutionPrimitive.STANDBY,
        DailyStorageIntent.GRID_REQUIREMENT: ExecutionPrimitive.CHARGE_AT_POWER,
        DailyStorageIntent.STORAGE_EXPORT: ExecutionPrimitive.DISCHARGE_AT_POWER,
    }[intent]


def _path_intervals(
    schedule: DailyReferenceIntentSchedule,
) -> tuple[DailyReferenceIntentInterval, ...]:
    """Coalesce logical modes while retaining exact export-energy intervals."""

    intervals: list[DailyReferenceIntentInterval] = []
    for interval in schedule.intervals:
        if (
            intervals
            and intervals[-1].ends_at == interval.starts_at
            and intervals[-1].intent is interval.intent
            and interval.intent is not DailyStorageIntent.STORAGE_EXPORT
        ):
            intervals[-1] = DailyReferenceIntentInterval(
                starts_at=intervals[-1].starts_at,
                ends_at=interval.ends_at,
                intent=interval.intent,
            )
        else:
            intervals.append(interval)
    return tuple(intervals)


def _path(
    *,
    snapshot: PlanningInputSnapshot,
    schedule: DailyReferenceIntentSchedule,
    candidate_id: str,
    family: CandidateFamily,
    confidence: float,
    opportunity_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    strategy_version: int,
    projected_result: DailyReferenceStrategyResult | None,
    constraint_ids: tuple[str, ...],
) -> DomainEnergyPath:
    storage = snapshot.current_storage_states[0]
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    segments = tuple(
        PathSegment(
            segment_id=_id("mep-segment", f"{candidate_id}|{index}"),
            order=index,
            execution_scope_id=storage.execution_scope_id,
            starts_at=interval.starts_at,
            ends_at=interval.ends_at,
            primitive=_primitive(interval.intent),
            capability_id=storage.capability_id,
            purpose=f"mep:{interval.intent.value}",
            evidence_ids=tuple(dict.fromkeys((schedule.schedule_id, *evidence_ids))),
            requested_power_w=(
                limits.maximum_charge_input_power_w
                if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
                else limits.maximum_discharge_output_power_w
                if interval.intent is DailyStorageIntent.STORAGE_EXPORT
                else None
            ),
            charge_source_policy=(
                ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED
                if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
                else ChargeSourcePolicy.PV_ONLY
                if interval.intent is DailyStorageIntent.NOM
                else None
            ),
        )
        for index, interval in enumerate(_path_intervals(schedule), start=1)
    )
    states: tuple[ProjectedEnergyState, ...] = ()
    if projected_result is not None:
        central = next(
            item
            for item in projected_result.run.simulation.trajectories
            if item.scenario is PVScenario.CENTRAL
        )
        states = tuple(
            ProjectedEnergyState(
                at=interval.ends_at,
                confidence=interval.confidence,
                household_import_w=0.0,
                household_export_w=0.0,
                pv_production_w=0.0,
                household_demand_w=0.0,
                battery_soc=(interval.storage_energy_at_end_wh / storage.usable_capacity_wh),
                storage_energy_wh=interval.storage_energy_at_end_wh,
                conversion_losses_w=0.0,
            )
            for interval in central.intervals
        )
    capability_set = snapshot.capability_snapshot_set
    assert capability_set is not None
    return DomainEnergyPath(
        path_id=_id("mep-energy-path", candidate_id),
        snapshot_id=snapshot.snapshot_id,
        family=family,
        horizon_start=schedule.horizon_start,
        horizon_end=schedule.horizon_end,
        segments=segments,
        projected_states=states,
        opportunity_ids=opportunity_ids,
        constraint_ids=constraint_ids,
        capability_ids=(storage.capability_id,),
        strategy_version=strategy_version,
        mapping_version=capability_set.mapping_version,
        assumptions=("lower-central-upper PV scenarios", "fresh Planning Input"),
        confidence=confidence,
    )


def _objective_outcomes(
    *,
    financial: float,
    self_consumption: float,
    reserve: float,
    confidence: float,
    evidence_ids: tuple[str, ...],
) -> tuple[ObjectiveOutcome, ...]:
    return (
        ObjectiveOutcome(
            ObjectiveKind.FINANCIAL_RESULT,
            financial,
            ComparisonDirection.HIGHER_IS_BETTER,
            "EUR",
            confidence,
            evidence_ids,
        ),
        ObjectiveOutcome(
            ObjectiveKind.SELF_CONSUMPTION,
            self_consumption,
            ComparisonDirection.HIGHER_IS_BETTER,
            "Wh",
            confidence,
            evidence_ids,
        ),
        ObjectiveOutcome(
            ObjectiveKind.RESERVE_AVAILABILITY,
            reserve,
            ComparisonDirection.HIGHER_IS_BETTER,
            "Wh",
            confidence,
            evidence_ids,
        ),
    )


def _native_metrics(
    result: DailyReferenceStrategyResult,
    *,
    baseline: DailyReferenceStrategyResult,
    wear_eur_per_export_kwh: float,
) -> tuple[float, float, float, float, float]:
    run = result.run
    baseline_assessments = {
        item.scenario: item for item in baseline.run.assessment.assessments
    }
    assessments = {item.scenario: item for item in run.assessment.assessments}
    financial = min(
        item.net_financial_result_eur
        - max(
            0.0,
            assessments[item.scenario].storage_to_grid_output_wh
            - baseline_assessments[item.scenario].storage_to_grid_output_wh,
        )
        / 1000.0
        * wear_eur_per_export_kwh
        for item in run.financial.paths
    )
    self_consumption = min(
        assessment.usable_pv_wh - assessment.pv_to_grid_wh
        for assessment in run.assessment.assessments
    )
    reserve = min(
        assessment.minimum_storage_energy_observed_wh - trajectory.minimum_storage_energy_wh
        for assessment, trajectory in zip(
            run.assessment.assessments,
            run.simulation.trajectories,
            strict=True,
        )
    )
    confidence = min(item.minimum_confidence for item in run.assessment.assessments)
    grid_to_storage = max(
        sum(interval.grid_to_storage_input_wh for interval in trajectory.intervals)
        for trajectory in run.simulation.trajectories
    )
    return financial, self_consumption, reserve, confidence, grid_to_storage


def _storage_requirement_evidence(
    *,
    snapshot: PlanningInputSnapshot,
    portfolio: MarketDailyCandidatePortfolio,
    baseline: DailyReferenceStrategyResult,
) -> tuple[ProjectedHouseholdEnergyBalance, StorageEnergyRequirement]:
    """Project the ADR-037 requirement that constrains every complete path."""

    storage = snapshot.current_storage_states[0]
    limits = next(
        item
        for item in snapshot.storage_physical_limits
        if item.execution_scope_id == storage.execution_scope_id
        and item.capability_id == storage.capability_id
    )
    trajectory = next(
        item
        for item in baseline.run.simulation.trajectories
        if item.scenario is PVScenario.LOWER
    )
    balance_id = _id(
        "mep-projected-household-balance",
        f"{snapshot.snapshot_id}|{portfolio.required_by.isoformat()}",
    )
    intervals = tuple(
        ProjectedHouseholdEnergyBalanceInterval(
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            current_usable_storage_energy_wh=item.storage_energy_at_start_wh,
            expected_usable_pv_energy_wh=item.usable_pv_wh,
            planned_grid_energy_wh=(
                item.grid_to_household_wh + item.grid_to_storage_input_wh
            ),
            household_load_forecast_energy_wh=item.household_demand_wh,
            known_future_demand_energy_wh=0.0,
            conversion_losses_wh=(
                item.storage_charge_loss_wh + item.storage_discharge_loss_wh
            ),
            other_planned_household_energy_flows_wh=-(
                item.pv_to_grid_wh + item.storage_to_grid_output_wh
            ),
            projected_storage_energy_wh=item.storage_energy_at_end_wh,
            confidence=item.confidence,
            evidence_ids=item.evidence_ids,
        )
        for item in trajectory.intervals
    )
    balance = ProjectedHouseholdEnergyBalance(
        balance_id=balance_id,
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        storage_state_id=storage.storage_state_id,
        intervals=intervals,
    )
    relevant = tuple(
        item for item in intervals if item.starts_at < portfolio.required_by
    )
    evidence_ids = tuple(
        dict.fromkeys(
            (
                balance_id,
                *(
                    evidence_id
                    for interval in relevant
                    for evidence_id in interval.evidence_ids
                ),
                METHOD_VERSION,
            )
        )
    )
    target_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
    requirement = StorageEnergyRequirement(
        requirement_id=_id(
            "mep-storage-requirement",
            f"{balance_id}|{target_energy_wh}|{portfolio.required_by.isoformat()}",
        ),
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        storage_state_id=storage.storage_state_id,
        projected_balance_id=balance_id,
        required_energy_wh=target_energy_wh,
        required_soc=limits.maximum_soc,
        required_by=portfolio.required_by,
        reason="household_demand",
        confidence=min((item.confidence for item in relevant), default=0.0),
        evidence_ids=evidence_ids,
        reserve_contribution_wh=limits.minimum_soc * storage.usable_capacity_wh,
        confidence_method_version="mep-household-requirement-minimum-confidence:v1",
    )
    return balance, requirement


def _target_reached_by_requirement(
    *,
    result: DailyReferenceStrategyResult | None,
    market: MarketRouteAssessment | None,
    requirement: StorageEnergyRequirement,
    current_storage_energy_wh: float,
) -> bool:
    """Return whether every scenario reaches the required state by its deadline."""

    if current_storage_energy_wh + 1e-6 >= requirement.required_energy_wh:
        return True
    if market is not None:
        return all(
            any(
                checkpoint.at <= requirement.required_by
                and checkpoint.energy_wh + 1e-6 >= requirement.required_energy_wh
                for checkpoint in scenario.storage_energy_checkpoints
            )
            for scenario in market.scenario_evidence
        )
    if result is None:
        return False
    return all(
        trajectory.target_reached_at is not None
        and trajectory.target_reached_at <= requirement.required_by
        for trajectory in result.run.simulation.trajectories
    )


def _recoverability(
    *,
    schedule: DailyReferenceIntentSchedule,
    grid_to_storage_input_wh: float,
    usable_capacity_wh: float,
) -> float:
    """Prefer less grid dependence, then the last equally safe charge window."""

    charge_starts = tuple(
        item.starts_at
        for item in schedule.intervals
        if item.intent is DailyStorageIntent.GRID_REQUIREMENT
    )
    horizon_seconds = (schedule.horizon_end - schedule.horizon_start).total_seconds()
    latest_fraction = (
        (max(charge_starts) - schedule.horizon_start).total_seconds() / horizon_seconds
        if charge_starts
        else 1.0
    )
    grid_independence = 1.0 - min(
        1.0,
        grid_to_storage_input_wh / usable_capacity_wh,
    )
    return grid_independence * 0.999999 + latest_fraction * 0.000001


def _committed_schedule(
    *,
    snapshot: PlanningInputSnapshot,
    commitment: ActivePlanCommitment,
    reference: DailyReferenceIntentSchedule,
) -> tuple[DailyReferenceIntentSchedule, tuple[str, ...]]:
    stored = commitment.segments or (
        CommittedPlanSegment(
            starts_at=commitment.starts_at,
            ends_at=commitment.ends_at,
            primitive=commitment.primitive,
            source_policy=(
                commitment.source_policy if commitment.source_policy != "not_applicable" else None
            ),
        ),
    )
    intervals: list[DailyReferenceIntentInterval] = []
    reasons: list[str] = []
    intents = {
        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY.value: DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY,
        ExecutionPrimitive.BALANCE_BIDIRECTIONAL.value: DailyStorageIntent.NOM,
        ExecutionPrimitive.STANDBY.value: DailyStorageIntent.STANDBY,
        ExecutionPrimitive.CHARGE_AT_POWER.value: DailyStorageIntent.GRID_REQUIREMENT,
        ExecutionPrimitive.DISCHARGE_AT_POWER.value: DailyStorageIntent.STORAGE_EXPORT,
    }
    for grid in reference.intervals:
        segment = next(
            (
                item
                for item in stored
                if item.starts_at <= grid.starts_at and item.ends_at >= grid.ends_at
            ),
            None,
        )
        if segment is None:
            reasons.append("committed_schedule_gap")
            intent = DailyStorageIntent.STANDBY
            export_target = 0.0
        elif segment.primitive not in intents:
            reasons.append("committed_primitive_unsupported")
            intent = DailyStorageIntent.STANDBY
            export_target = 0.0
        else:
            intent = intents[segment.primitive]
            export_target = segment.storage_export_target_wh or 0.0
            if intent is DailyStorageIntent.STORAGE_EXPORT and export_target <= 0.0:
                reasons.append("committed_export_target_missing")
                intent = DailyStorageIntent.STANDBY
        intervals.append(
            DailyReferenceIntentInterval(grid.starts_at, grid.ends_at, intent, export_target)
        )
    return (
        DailyReferenceIntentSchedule(
            schedule_id=_id("mep-committed-schedule", commitment.plan_id),
            snapshot_id=snapshot.snapshot_id,
            horizon_start=reference.horizon_start,
            horizon_end=reference.horizon_end,
            intervals=tuple(intervals),
            method_version=METHOD_VERSION,
        ),
        tuple(dict.fromkeys(reasons)),
    )


def _simulate_committed(
    *,
    snapshot: PlanningInputSnapshot,
    schedule: DailyReferenceIntentSchedule,
    conversion_model: StorageConversionModel,
) -> DailyReferenceStrategyResult:
    inputs = IndependentDailyReferenceAdapter().build_inputs(
        snapshot,
        horizon_end=schedule.horizon_end,
        maximum_duration=schedule.horizon_end - schedule.horizon_start,
    )
    tariffs = IndependentDailyTariffAdapter().build(snapshot, horizon_end=schedule.horizon_end)
    portfolio = IndependentDailyReferencePortfolioProducer().produce(
        snapshot_id=snapshot.snapshot_id,
        household=inputs.household,
        pv_scenarios=inputs.pv_scenarios,
        storage_state=inputs.storage,
        conversion_model=conversion_model,
        tariffs=tariffs,
        intent_schedules=(schedule,),
        minimum_storage_energy_wh=inputs.minimum_storage_energy_wh,
        target_storage_energy_wh=inputs.target_storage_energy_wh,
        maximum_charge_input_power_w=inputs.maximum_charge_input_power_w,
        maximum_discharge_output_power_w=inputs.maximum_discharge_output_power_w,
    )
    IndependentDailyCandidateEngine().build_portfolio(portfolio)
    return portfolio.strategy_results[0]


def produce_mep_comparable_portfolio(
    *,
    snapshot: PlanningInputSnapshot,
    portfolio: MarketDailyCandidatePortfolio,
    conversion_model: StorageConversionModel,
    incumbent: ActivePlanCommitment | None,
    financial_equivalence_margin_eur: float,
) -> MepComparablePortfolio:
    """Produce every challenger and a freshly simulated incumbent before Evaluation."""

    strategy = _strategy(snapshot)
    native_results = {
        item.intent_schedule.schedule_id: item
        for item in portfolio.native_observation.observer_result.portfolio.strategy_results
    }
    native_candidates = {
        item.intent_schedule_id: item
        for item in portfolio.native_observation.observer_result.candidate_set.candidates
    }
    baseline = next(
        item
        for item in native_results.values()
        if all(
            interval.intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
            for interval in item.intent_schedule.intervals
        )
    )
    projected_balance, storage_requirement = _storage_requirement_evidence(
        snapshot=snapshot,
        portfolio=portfolio,
        baseline=baseline,
    )
    route_ids = {item.route_id: item.opportunity_ids for item in portfolio.market_routes}
    source_rows: list[MepCandidateSource] = []
    rows: list[_CandidateRow] = []
    for schedule_id, native_result in native_results.items():
        native_candidate = native_candidates[schedule_id]
        rows.append(
            _CandidateRow(
                native_candidate.candidate_id,
                native_result.intent_schedule,
                native_candidate,
                None,
                None,
                native_result,
                (),
                (native_candidate.source_run_id,),
            )
        )
    for assessment in portfolio.route_assessments:
        candidate_id = _id("mep-market-candidate", assessment.market_schedule_id)
        rows.append(
            _CandidateRow(
                candidate_id,
                assessment.intent_schedule,
                None,
                assessment,
                None,
                None,
                route_ids.get(assessment.route_id, ()),
                (assessment.route_id, assessment.market_schedule_id),
            )
        )

    incumbent_id: str | None = None
    incumbent_reasons: tuple[str, ...] = ()
    if incumbent is not None:
        reference = next(iter(native_results.values())).intent_schedule
        schedule, incumbent_reasons = _committed_schedule(
            snapshot=snapshot, commitment=incumbent, reference=reference
        )
        incumbent_id = _id("mep-committed-candidate", incumbent.plan_id)
        simulated = (
            None
            if incumbent_reasons
            else _simulate_committed(
                snapshot=snapshot, schedule=schedule, conversion_model=conversion_model
            )
        )
        rows.append(
            _CandidateRow(
                incumbent_id,
                schedule,
                None,
                None,
                incumbent,
                simulated,
                (),
                tuple(
                    dict.fromkeys((incumbent.plan_id, incumbent.schedule_id or incumbent.plan_id))
                ),
            )
        )

    candidates: list[DomainCandidate] = []
    paths: list[DomainEnergyPath] = []
    outcomes: list[DomainCandidateOutcome] = []
    diagnostics: list[MepCandidateOutcome] = []
    limits = snapshot.storage_physical_limits[0]
    for row in rows:
        candidate_id = row.candidate_id
        schedule = row.schedule
        native = row.native
        market = row.market
        committed = row.commitment
        result = row.result
        opportunity_ids = row.opportunity_ids
        evidence_ids = row.evidence_ids
        reasons: list[str] = list(incumbent_reasons if committed is not None else ())
        if market is not None:
            financial = min(item.total_financial_result_eur for item in market.scenario_evidence)
            self_consumption = min(item.self_consumed_pv_wh for item in market.scenario_evidence)
            reserve = min(item.reserve_margin_wh for item in market.scenario_evidence)
            confidence = min(item.minimum_confidence for item in market.scenario_evidence)
            grid_to_storage = max(
                item.grid_to_storage_input_wh for item in market.scenario_evidence
            )
            if not market.physically_admissible:
                reasons.append("market_route_physically_inadmissible")
        elif result is not None:
            (
                financial,
                self_consumption,
                reserve,
                confidence,
                grid_to_storage,
            ) = _native_metrics(
                result,
                baseline=baseline,
                wear_eur_per_export_kwh=portfolio.wear_eur_per_export_kwh,
            )
            built = (
                IndependentDailyCandidateEngine()
                .build_portfolio(
                    type(portfolio.native_observation.observer_result.portfolio)(
                        portfolio_id=portfolio.native_observation.observer_result.portfolio.portfolio_id,
                        snapshot_id=snapshot.snapshot_id,
                        tariff_schedule_id=portfolio.native_observation.observer_result.portfolio.tariff_schedule_id,
                        strategy_results=(result,),
                        observer_only=True,
                        ranking_permitted=False,
                        method_version=portfolio.native_observation.observer_result.portfolio.method_version,
                    )
                )
                .candidates[0]
            )
            if not built.complete_across_scenarios:
                reasons.append("physical_path_incomplete")
            if not built.reserve_respected_across_scenarios:
                reasons.append("reserve_not_respected")
            if not built.target_reached_across_scenarios:
                reasons.append("target_not_reached")
        else:
            financial = self_consumption = reserve = 0.0
            confidence = 0.0
            grid_to_storage = snapshot.current_storage_states[0].usable_capacity_wh
            reasons.append("fresh_incumbent_simulation_unavailable")
        if not _target_reached_by_requirement(
            result=result,
            market=market,
            requirement=storage_requirement,
            current_storage_energy_wh=(
                snapshot.current_storage_states[0].current_stored_energy_wh
            ),
        ):
            reasons.append("storage_requirement_not_met_by_deadline")
        family = _family(native, incumbent=committed is not None)
        constraint_ids = tuple(
            dict.fromkeys((*limits.evidence_ids, storage_requirement.requirement_id))
        )
        path = _path(
            snapshot=snapshot,
            schedule=schedule,
            candidate_id=candidate_id,
            family=family,
            confidence=confidence,
            opportunity_ids=opportunity_ids,
            evidence_ids=evidence_ids,
            strategy_version=strategy.strategy_version,
            projected_result=result,
            constraint_ids=constraint_ids,
        )
        candidate = DomainCandidate(
            candidate_id,
            snapshot.snapshot_id,
            family,
            path.path_id,
            opportunity_ids,
            constraint_ids,
            strategy.strategy_version,
            path.capability_ids,
            path.assumptions,
            confidence,
        )
        validity = CandidateValidity.INVALID if reasons else CandidateValidity.VALID
        recoverability = _recoverability(
            schedule=schedule,
            grid_to_storage_input_wh=grid_to_storage,
            usable_capacity_wh=snapshot.current_storage_states[0].usable_capacity_wh,
        )
        switching = sum(
            left.intent is not right.intent
            for left, right in zip(schedule.intervals, schedule.intervals[1:], strict=False)
        )
        objective_values = _objective_outcomes(
            financial=financial,
            self_consumption=self_consumption,
            reserve=reserve,
            confidence=confidence,
            evidence_ids=evidence_ids,
        )
        outcome = DomainCandidateOutcome(
            candidate_id,
            objective_values,
            confidence,
            recoverability,
            len(path.segments),
            switching,
            "mep-segments:v1",
            validity,
            tuple(dict.fromkeys(reasons)),
            evidence_ids,
        )
        candidates.append(candidate)
        paths.append(path)
        outcomes.append(outcome)
        source_rows.append(MepCandidateSource(candidate_id, schedule, native, market, committed))
        diagnostics.append(
            MepCandidateOutcome(
                _id("mep-outcome", candidate_id),
                snapshot.run_id,
                snapshot.snapshot_id,
                candidate_id,
                path.path_id,
                schedule.horizon_start,
                schedule.horizon_end,
                committed is not None,
                validity.value,
                outcome.invalidity_reasons,
                financial,
                self_consumption,
                reserve,
                confidence,
                recoverability,
                outcome.execution_complexity,
                switching,
                evidence_ids,
                METHOD_VERSION,
                financial_equivalence_margin_eur,
                next(
                    (
                        interval.starts_at
                        for interval in schedule.intervals
                        if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
                    ),
                    None,
                ),
                next(
                    (
                        interval.ends_at
                        for interval in reversed(schedule.intervals)
                        if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
                    ),
                    None,
                ),
                (
                    committed.target_energy_wh
                    if committed is not None
                    else limits.maximum_soc * snapshot.current_storage_states[0].usable_capacity_wh
                ),
            )
        )
    candidate_set = DomainCandidateSet(
        snapshot.snapshot_id, strategy.strategy_version, tuple(candidates), tuple(paths), ()
    )
    outcome_set = DomainCandidateOutcomeSet(
        snapshot.snapshot_id,
        strategy.strategy_version,
        EvaluationEngine.candidate_set_reference(candidate_set),
        tuple(outcomes),
    )
    return MepComparablePortfolio(
        candidate_set,
        outcome_set,
        strategy,
        tuple(source_rows),
        tuple(diagnostics),
        incumbent_id,
        projected_balance,
        storage_requirement,
    )
