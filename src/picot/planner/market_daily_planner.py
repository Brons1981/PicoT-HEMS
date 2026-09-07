"""Independent Market Daily Planner built directly from Planning Input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from picot.architecture_ownership import architecture_ownership
from picot.domain.daily_reference_intent import (
    DailyReferenceIntentInterval,
    DailyReferenceIntentSchedule,
    DailyStorageIntent,
)
from picot.domain.daily_reference_portfolio import DailyReferenceStrategyResult
from picot.domain.daily_reference_simulation import DailyReferenceTrajectory, PVScenario
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.domain.storage_energy_inventory import StorageEnergyInventory
from picot.planner.independent_daily_reference_portfolio import (
    IndependentDailyReferencePortfolioProducer,
)
from picot.v2.contracts import OpportunitySet, PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    IndependentDailyReferenceAdapter,
)
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
from picot.v2.opportunity_engine import (
    HIGH_EXPORT_VALUE_WINDOW,
    LOWEST_PRICE_WINDOW,
    NEGATIVE_PRICE_WINDOW,
    OpportunityEngine,
    PriceOpportunityConfig,
)

ARCHITECTURE_OWNERSHIP = architecture_ownership("mep_candidate_generation", __name__)
METHOD_VERSION = "market-daily-planner:v14"
MARKET_DAILY_MAXIMUM_DURATION = timedelta(hours=36)


def _household_energy_requirement_deadline(
    observation: DailyReferenceStrategyObservation,
) -> datetime:
    """Return the first physically reachable household-storage deadline.

    ADR-017 and ADR-037 make the projected household energy balance authoritative
    for when stored energy is needed.  This is MEP-native physical evidence; it
    is not a CP deadline and it does not select a charging window.
    """

    baseline_schedule_id = observation.strategy_space.schedules[0].schedule_id
    baseline = next(
        item
        for item in observation.observer_result.portfolio.strategy_results
        if item.intent_schedule.schedule_id == baseline_schedule_id
    )
    dependency_starts = tuple(
        interval.starts_at
        for trajectory in baseline.run.simulation.trajectories
        for interval in trajectory.intervals
        if interval.grid_to_household_wh > 1e-6
    )
    dependency_start = min(
        dependency_starts,
        default=baseline.intent_schedule.horizon_end,
    )
    if dependency_start == baseline.intent_schedule.horizon_end:
        return dependency_start

    immediate_recovery_times = tuple(
        max(
            trajectory.target_reached_at
            for trajectory in result.run.simulation.trajectories
            if trajectory.target_reached_at is not None
        )
        for result in observation.observer_result.portfolio.strategy_results
        if (
            any(
                interval.starts_at == result.intent_schedule.horizon_start
                and interval.intent in {DailyStorageIntent.NOM, DailyStorageIntent.GRID_REQUIREMENT}
                for interval in result.intent_schedule.intervals
            )
            and all(
                trajectory.target_reached_at is not None
                for trajectory in result.run.simulation.trajectories
            )
        )
    )
    earliest_recovery = min(
        immediate_recovery_times,
        default=baseline.intent_schedule.horizon_end,
    )
    return max(dependency_start, earliest_recovery)


@dataclass(frozen=True, slots=True)
class MarketTradingPolicy:
    margin_fraction: float = 0.10
    wear_eur_per_export_kwh: float = 0.05
    market_routes_enabled: bool = True
    maximum_trading_soc_fraction: float = 0.25
    additional_reserve_fraction: float = 0.10
    minimum_total_route_profit_eur: float = 0.05
    preserve_pv_during_grid_charge: bool = False
    saldering_energy_tax_credit_enabled: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.margin_fraction <= 1.0:
            raise ValueError("MEP trading margin must be between 0 and 1")
        if not 0.0 <= self.wear_eur_per_export_kwh <= 1.0:
            raise ValueError("MEP wear cost must be between 0 and 1 EUR/kWh")
        if not 0.0 <= self.maximum_trading_soc_fraction <= 1.0:
            raise ValueError("MEP trading SoC budget must be between 0 and 1")
        if not 0.0 <= self.additional_reserve_fraction <= 1.0:
            raise ValueError("MEP additional reserve must be between 0 and 1")
        if not 0.0 <= self.minimum_total_route_profit_eur <= 100.0:
            raise ValueError("MEP minimum route profit must be between 0 and 100 EUR")

    def minimum_export_rate(self, recharge_rate: float, rte: float) -> float:
        if not 0.5 <= rte <= 1.0:
            raise ValueError("MEP RTE must be between 0.5 and 1.0")
        return recharge_rate / rte * (1.0 + self.margin_fraction) + self.wear_eur_per_export_kwh


@dataclass(frozen=True, slots=True)
class MarketCapacityRoute:
    """Bounded capacity preparation for one truly negative import window."""

    route_id: str
    snapshot_id: str
    opportunity_ids: tuple[str, ...]
    window_starts_at: datetime
    window_ends_at: datetime
    maximum_charge_input_wh: float
    reserved_storage_room_wh: float
    storage_energy_ceiling_before_window_wh: float
    required_pre_window_discharge_output_wh: float
    opportunity_window_starts_at: datetime
    opportunity_window_ends_at: datetime
    charge_safety_margin_seconds: float
    reason: str
    method_version: str
    export_window_starts_at: datetime | None = None
    export_window_ends_at: datetime | None = None
    route_kind: str = "negative_capacity"
    average_export_eur_per_kwh: float | None = None
    average_recharge_eur_per_kwh: float | None = None
    minimum_export_eur_per_kwh: float | None = None

    def __post_init__(self) -> None:
        if not self.opportunity_ids or any(not item.strip() for item in self.opportunity_ids):
            raise ValueError("MEP market route opportunity lineage must be explicit.")
        if self.window_ends_at <= self.window_starts_at:
            raise ValueError("MEP market window must have positive duration.")
        if self.opportunity_window_ends_at <= self.opportunity_window_starts_at:
            raise ValueError("MEP source opportunity window must have positive duration.")
        if not (
            self.opportunity_window_starts_at
            <= self.window_starts_at
            < self.window_ends_at
            <= self.opportunity_window_ends_at
        ):
            raise ValueError("MEP market window must remain inside its source opportunity.")
        if self.charge_safety_margin_seconds < 0.0:
            raise ValueError("MEP charge safety margin must not be negative.")
        if (
            min(
                self.maximum_charge_input_wh,
                self.reserved_storage_room_wh,
                self.storage_energy_ceiling_before_window_wh,
                self.required_pre_window_discharge_output_wh,
            )
            < 0.0
        ):
            raise ValueError("MEP capacity-route energy must not be negative.")
        if self.route_kind not in {
            "negative_capacity",
            "grid_trade",
        }:
            raise ValueError("MEP market-route kind must be explicit.")
        if (self.export_window_starts_at is None) != (self.export_window_ends_at is None):
            raise ValueError("MEP export window must be complete.")
        if (
            self.export_window_starts_at is not None
            and self.export_window_ends_at is not None
            and self.export_window_ends_at <= self.export_window_starts_at
        ):
            raise ValueError("MEP export window must have positive duration.")


@dataclass(frozen=True, slots=True)
class _MarketOpportunityWindow:
    opportunity_id: str
    intervals: tuple[DailyReferenceTariffInterval, ...]


def _duration_hours(interval: DailyReferenceTariffInterval) -> float:
    return (interval.ends_at - interval.starts_at).total_seconds() / 3600.0


def _peak_anchored_export_windows(
    intervals: tuple[DailyReferenceTariffInterval, ...],
) -> tuple[tuple[DailyReferenceTariffInterval, ...], ...]:
    """Grow contiguous export windows from the highest priced interval.

    Every returned window contains the absolute price peak.  Additional
    capacity is added from the more valuable adjacent interval so a vendor
    window remains contiguous without allowing a sub-cent total-result tie to
    move the export away from the actual peak.
    """

    if not intervals:
        return ()
    peak_index = max(
        range(len(intervals)),
        key=lambda index: (
            intervals[index].export_eur_per_kwh,
            -index,
        ),
    )
    left = peak_index
    right = peak_index
    windows: list[tuple[DailyReferenceTariffInterval, ...]] = [(intervals[peak_index],)]
    while left > 0 or right + 1 < len(intervals):
        left_rate = intervals[left - 1].export_eur_per_kwh if left > 0 else float("-inf")
        right_rate = (
            intervals[right + 1].export_eur_per_kwh if right + 1 < len(intervals) else float("-inf")
        )
        if right_rate > left_rate:
            right += 1
        else:
            left -= 1
        windows.append(intervals[left : right + 1])
    return tuple(windows)


@dataclass(frozen=True, slots=True)
class MarketRouteStorageCheckpoint:
    """One scenario-specific storage-energy point retained for monitoring."""

    at: datetime
    energy_wh: float

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("MEP storage checkpoint must be timezone-aware.")
        if self.energy_wh < 0.0:
            raise ValueError("MEP storage checkpoint energy must be non-negative.")


@dataclass(frozen=True, slots=True)
class MarketRouteScenarioEvidence:
    """Physical admission evidence for one route and one PV scenario."""

    scenario: PVScenario
    physically_complete: bool
    reserve_respected: bool
    target_reached_during_horizon: bool
    target_held_at_horizon_end: bool
    target_storage_energy_wh: float
    minimum_storage_energy_wh: float
    minimum_storage_energy_observed_wh: float
    storage_energy_at_horizon_end_wh: float
    baseline_storage_energy_at_horizon_end_wh: float
    target_shortfall_wh: float
    reserve_margin_wh: float
    grid_to_storage_input_wh: float
    explicit_charge_pv_to_storage_input_wh: float
    explicit_charge_grid_to_storage_input_wh: float
    household_demand_wh: float
    incremental_financial_result_eur: float
    exported_energy_kwh: float
    storage_energy_checkpoints: tuple[MarketRouteStorageCheckpoint, ...] = ()
    self_consumed_pv_wh: float = 0.0
    grid_to_household_wh: float = 0.0
    conversion_losses_wh: float = 0.0
    minimum_confidence: float = 0.0
    total_financial_result_eur: float = 0.0

    def __post_init__(self) -> None:
        if (
            self.explicit_charge_pv_to_storage_input_wh < 0.0
            or self.explicit_charge_grid_to_storage_input_wh < 0.0
        ):
            raise ValueError("MEP explicit-charge energy evidence must be non-negative.")
        if self.explicit_charge_grid_to_storage_input_wh > self.grid_to_storage_input_wh + 1e-6:
            raise ValueError("MEP explicit grid input must reconcile with route input.")
        checkpoint_times = tuple(item.at for item in self.storage_energy_checkpoints)
        if checkpoint_times != tuple(sorted(set(checkpoint_times))):
            raise ValueError("MEP storage checkpoints must be unique and ordered.")
        if (
            min(
                self.self_consumed_pv_wh,
                self.grid_to_household_wh,
                self.conversion_losses_wh,
            )
            < 0.0
        ):
            raise ValueError("MEP comparable energy outcomes must be non-negative.")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("MEP scenario confidence must be bounded.")


@dataclass(frozen=True, slots=True)
class MarketRouteAssessment:
    """Complete physical and incremental financial admission of one MEP route."""

    route_id: str
    source_native_schedule_id: str
    market_schedule_id: str
    intent_schedule: DailyReferenceIntentSchedule
    physically_admissible: bool
    incremental_wear_eur: float
    worst_case_incremental_result_eur: float
    minimum_incremental_result_eur_per_exported_kwh: float
    admitted: bool
    admission_reason: str
    scenario_evidence: tuple[MarketRouteScenarioEvidence, ...]
    method_version: str
    minimum_total_route_profit_eur: float = 0.05

    def __post_init__(self) -> None:
        if not all(
            (
                self.route_id.strip(),
                self.source_native_schedule_id.strip(),
                self.market_schedule_id.strip(),
                self.method_version.strip(),
            )
        ):
            raise ValueError("MEP route assessment lineage must be explicit.")
        if self.incremental_wear_eur < 0.0:
            raise ValueError("MEP incremental wear must not be negative.")
        if self.intent_schedule.schedule_id != self.market_schedule_id:
            raise ValueError("MEP assessed schedule lineage must reconcile.")
        expected_admission = (
            self.physically_admissible
            and self.worst_case_incremental_result_eur >= self.minimum_total_route_profit_eur
            and self.minimum_incremental_result_eur_per_exported_kwh > 0.0
        )
        if self.admitted != expected_admission:
            raise ValueError("MEP route admission must reconcile.")
        if not self.admission_reason.strip():
            raise ValueError("MEP route admission reason must be explicit.")
        scenarios = tuple(item.scenario for item in self.scenario_evidence)
        if set(scenarios) != set(PVScenario) or len(scenarios) != len(PVScenario):
            raise ValueError("MEP route evidence requires all three PV scenarios.")


@dataclass(frozen=True, slots=True)
class MarketDailyPlan:
    """One complete MEP result derived only from its Planning Input."""

    planner_id: str
    planner_name: str
    snapshot_id: str
    native_observation: DailyReferenceStrategyObservation
    market_routes: tuple[MarketCapacityRoute, ...]
    route_assessments: tuple[MarketRouteAssessment, ...]
    winning_source: str
    reason: str
    dispatch_authority: bool
    current_intent: DailyStorageIntent | None
    current_interval_ends_at: datetime | None
    method_version: str
    round_trip_efficiency: float
    trading_margin_fraction: float
    wear_eur_per_export_kwh: float
    minimum_total_route_profit_eur: float = 0.05

    def __post_init__(self) -> None:
        if self.planner_id != "mep" or self.planner_name != "Markt Etmaal Planner":
            raise ValueError("MEP identity must remain explicit.")
        if self.native_observation.snapshot_id != self.snapshot_id:
            raise ValueError("MEP native plan must share its Planning Input snapshot.")
        if not self.method_version.strip():
            raise ValueError("MEP method version must be explicit.")
        if not 0.5 <= self.round_trip_efficiency <= 1.0:
            raise ValueError("MEP plan RTE must be between 0.5 and 1.0")
        admitted = any(item.admitted for item in self.route_assessments)
        expected_source = "market_route" if admitted else "mep_native_plan"
        if self.winning_source != expected_source:
            raise ValueError("MEP winner source must reconcile with route admission.")
        if (self.current_intent is None) != (self.current_interval_ends_at is None):
            raise ValueError("MEP current intent and interval end must be paired.")


@dataclass(frozen=True, slots=True)
class MarketDailyCandidatePortfolio:
    """Unselected MEP candidate and simulation evidence."""

    snapshot_id: str
    native_observation: DailyReferenceStrategyObservation
    market_routes: tuple[MarketCapacityRoute, ...]
    route_assessments: tuple[MarketRouteAssessment, ...]
    recovery_outside_horizon: bool
    round_trip_efficiency: float
    trading_margin_fraction: float
    wear_eur_per_export_kwh: float
    minimum_total_route_profit_eur: float
    method_version: str
    required_by: datetime
    preserve_pv_during_grid_charge: bool = False

    def __post_init__(self) -> None:
        if self.native_observation.snapshot_id != self.snapshot_id:
            raise ValueError("MEP portfolio must share one Planning Input snapshot.")
        if not 0.5 <= self.round_trip_efficiency <= 1.0:
            raise ValueError("MEP portfolio RTE must be between 0.5 and 1.0")
        if not self.method_version.strip():
            raise ValueError("MEP portfolio method version must be explicit.")
        if self.required_by.tzinfo is None or self.required_by.utcoffset() is None:
            raise ValueError("MEP storage requirement deadline must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class MarketDailyPlannerDiagnostics:
    """Observational MEP phase timings; never consumed by planner policy."""

    native_plan_ms: float
    tariff_build_ms: float
    market_route_build_ms: float
    market_route_assessment_ms: float
    winner_selection_ms: float
    planner_total_ms: float
    native_candidate_count: int
    market_route_count: int
    route_assessment_count: int


class MarketDailyPlanner:
    """Generate unselected MEP candidates without consuming CP or EP output."""

    def plan(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy | None = None,
        dispatch_authority: bool = False,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory: StorageEnergyInventory | None = None,
        required_by: datetime | None = None,
        opportunities: OpportunitySet | None = None,
        maximum_duration: timedelta = MARKET_DAILY_MAXIMUM_DURATION,
    ) -> MarketDailyPlan:
        portfolio, _ = self.generate_with_diagnostics(
            snapshot=snapshot,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            storage_inventory=storage_inventory,
            required_by=required_by,
            opportunities=opportunities,
            maximum_duration=maximum_duration,
        )
        from picot.planner.market_daily_evaluation_engine import (
            MarketDailyEvaluationEngine,
        )

        return MarketDailyEvaluationEngine().evaluate(
            snapshot=snapshot,
            portfolio=portfolio,
            dispatch_authority=dispatch_authority,
        )

    def plan_with_diagnostics(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy | None = None,
        dispatch_authority: bool = False,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory: StorageEnergyInventory | None = None,
        required_by: datetime | None = None,
        opportunities: OpportunitySet | None = None,
        maximum_duration: timedelta = MARKET_DAILY_MAXIMUM_DURATION,
    ) -> tuple[MarketDailyPlan, MarketDailyPlannerDiagnostics]:
        portfolio, diagnostics = self.generate_with_diagnostics(
            snapshot=snapshot,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            storage_inventory=storage_inventory,
            required_by=required_by,
            opportunities=opportunities,
            maximum_duration=maximum_duration,
        )
        from picot.planner.market_daily_evaluation_engine import (
            MarketDailyEvaluationEngine,
        )

        started = perf_counter()
        plan = MarketDailyEvaluationEngine().evaluate(
            snapshot=snapshot,
            portfolio=portfolio,
            dispatch_authority=dispatch_authority,
        )
        return plan, MarketDailyPlannerDiagnostics(
            native_plan_ms=diagnostics.native_plan_ms,
            tariff_build_ms=diagnostics.tariff_build_ms,
            market_route_build_ms=diagnostics.market_route_build_ms,
            market_route_assessment_ms=diagnostics.market_route_assessment_ms,
            winner_selection_ms=round((perf_counter() - started) * 1000.0, 3),
            planner_total_ms=round(
                diagnostics.planner_total_ms + (perf_counter() - started) * 1000.0,
                3,
            ),
            native_candidate_count=diagnostics.native_candidate_count,
            market_route_count=diagnostics.market_route_count,
            route_assessment_count=diagnostics.route_assessment_count,
        )

    def generate_with_diagnostics(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy | None = None,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory: StorageEnergyInventory | None = None,
        required_by: datetime | None = None,
        opportunities: OpportunitySet | None = None,
        maximum_duration: timedelta = MARKET_DAILY_MAXIMUM_DURATION,
    ) -> tuple[MarketDailyCandidatePortfolio, MarketDailyPlannerDiagnostics]:
        planner_started = perf_counter()
        if maximum_duration <= timedelta(0):
            raise ValueError("MEP planning duration must be positive")
        maximum_duration = min(maximum_duration, MARKET_DAILY_MAXIMUM_DURATION)
        trading_policy = trading_policy or MarketTradingPolicy()
        opportunities = opportunities or OpportunityEngine().detect(
            snapshot,
            price_config=PriceOpportunityConfig(
                low_price_margin_eur_per_kwh=0.02,
                high_price_margin_eur_per_kwh=0.02,
                config_version="mep-compatibility-opportunities:v1",
            ),
        )
        phase_started = perf_counter()
        reference_adapter = IndependentDailyReferenceAdapter()
        preferred_grid_windows = tuple(
            (item.starts_at, item.ends_at)
            for item in opportunities.opportunities
            if item.kind == LOWEST_PRICE_WINDOW
        )
        native_observation = reference_adapter.observe(
            snapshot=snapshot,
            conversion_model=conversion_model,
            maximum_duration=maximum_duration,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            required_by=required_by,
            preferred_grid_windows=preferred_grid_windows,
            preserve_pv_during_grid_charge=(trading_policy.preserve_pv_during_grid_charge),
            saldering_energy_tax_credit_enabled=(
                trading_policy.saldering_energy_tax_credit_enabled
            ),
        )
        effective_required_by = required_by or _household_energy_requirement_deadline(
            native_observation
        )
        if required_by is None and effective_required_by < (
            native_observation.strategy_space.schedules[0].horizon_end
        ):
            native_observation = reference_adapter.observe(
                snapshot=snapshot,
                conversion_model=conversion_model,
                maximum_duration=maximum_duration,
                micro_charge_suppression_fraction=micro_charge_suppression_fraction,
                required_by=effective_required_by,
                preferred_grid_windows=preferred_grid_windows,
                preserve_pv_during_grid_charge=(trading_policy.preserve_pv_during_grid_charge),
                saldering_energy_tax_credit_enabled=(
                    trading_policy.saldering_energy_tax_credit_enabled
                ),
            )
        native_plan_ms = (perf_counter() - phase_started) * 1000.0
        horizon_end = native_observation.strategy_space.schedules[0].horizon_end
        phase_started = perf_counter()
        tariffs = IndependentDailyTariffAdapter().build(
            snapshot,
            horizon_end=horizon_end,
            saldering_energy_tax_credit_enabled=(
                trading_policy.saldering_energy_tax_credit_enabled
            ),
        )
        tariff_build_ms = (perf_counter() - phase_started) * 1000.0
        # Kept as an API-compatible observation only. A trade is bounded by
        # projected SoC and reserve; historical energy origin is not a route.
        _ = storage_inventory
        phase_started = perf_counter()
        routes, recovery_outside_horizon = self._market_routes(
            snapshot=snapshot,
            native_observation=native_observation,
            tariffs=tariffs,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            opportunities=opportunities,
        )
        market_route_build_ms = (perf_counter() - phase_started) * 1000.0
        phase_started = perf_counter()
        assessments = self._assess_routes(
            snapshot=snapshot,
            native_observation=native_observation,
            tariffs=tariffs,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            routes=routes,
            maximum_duration=maximum_duration,
        )
        market_route_assessment_ms = (perf_counter() - phase_started) * 1000.0
        portfolio = MarketDailyCandidatePortfolio(
            snapshot_id=snapshot.snapshot_id,
            native_observation=native_observation,
            market_routes=routes,
            route_assessments=assessments,
            recovery_outside_horizon=recovery_outside_horizon,
            round_trip_efficiency=(
                conversion_model.charge_efficiency * conversion_model.discharge_efficiency
            ),
            trading_margin_fraction=trading_policy.margin_fraction,
            wear_eur_per_export_kwh=trading_policy.wear_eur_per_export_kwh,
            minimum_total_route_profit_eur=(trading_policy.minimum_total_route_profit_eur),
            method_version=METHOD_VERSION,
            required_by=effective_required_by,
            preserve_pv_during_grid_charge=(trading_policy.preserve_pv_during_grid_charge),
        )
        candidates = native_observation.observer_result.candidate_set.candidates
        diagnostics = MarketDailyPlannerDiagnostics(
            native_plan_ms=round(native_plan_ms, 3),
            tariff_build_ms=round(tariff_build_ms, 3),
            market_route_build_ms=round(market_route_build_ms, 3),
            market_route_assessment_ms=round(market_route_assessment_ms, 3),
            winner_selection_ms=0.0,
            planner_total_ms=round((perf_counter() - planner_started) * 1000.0, 3),
            native_candidate_count=len(candidates),
            market_route_count=len(routes),
            route_assessment_count=len(assessments),
        )
        return portfolio, diagnostics

    @staticmethod
    def _representative_recovery_result(
        native_observation: DailyReferenceStrategyObservation,
    ) -> DailyReferenceStrategyResult:
        """Return one canonical PV-first recovery path already chosen by evaluation."""

        candidates = native_observation.observer_result.candidate_set.candidates
        best_ids = set(native_observation.observer_result.evaluation.best_candidate_ids)
        eligible = tuple(
            candidate for candidate in candidates if candidate.candidate_id in best_ids
        ) or tuple(
            candidate
            for candidate in candidates
            if candidate.complete_across_scenarios
            and candidate.target_reached_across_scenarios
            and candidate.reserve_respected_across_scenarios
        )
        if not eligible:
            baseline_schedule_id = native_observation.strategy_space.schedules[0].schedule_id
            return next(
                item
                for item in native_observation.observer_result.portfolio.strategy_results
                if item.intent_schedule.schedule_id == baseline_schedule_id
            )
        selected = min(
            eligible,
            key=lambda item: (
                item.average_charge_window_price_eur_per_kwh
                if item.average_charge_window_price_eur_per_kwh is not None
                else 0.0,
                item.candidate_id,
            ),
        )
        return next(
            item
            for item in native_observation.observer_result.portfolio.strategy_results
            if item.intent_schedule.schedule_id == selected.intent_schedule_id
        )

    @staticmethod
    def _weighted_recovery_rate(
        recovery_result: DailyReferenceStrategyResult,
        *,
        tariffs: DailyReferenceTariffSchedule,
    ) -> float:
        """Value PV, mixed and grid recovery as one weighted input price."""

        lower = next(
            item
            for item in recovery_result.run.simulation.trajectories
            if item.scenario is PVScenario.LOWER
        )
        tariff_by_interval = {(item.starts_at, item.ends_at): item for item in tariffs.intervals}
        pv_input_wh = sum(item.pv_to_storage_input_wh for item in lower.intervals)
        grid_input_wh = sum(item.grid_to_storage_input_wh for item in lower.intervals)
        total_input_wh = pv_input_wh + grid_input_wh
        if total_input_wh <= 1e-6:
            # Existing projected surplus has no acquisition dependency. Its
            # historic source is deliberately irrelevant to this trade.
            return 0.0
        grid_cost_eur = sum(
            item.grid_to_storage_input_wh
            / 1000.0
            * tariff_by_interval[(item.starts_at, item.ends_at)].import_eur_per_kwh
            for item in lower.intervals
            if item.grid_to_storage_input_wh > 0.0
        )
        return grid_cost_eur / (total_input_wh / 1000.0)

    @staticmethod
    def _storage_energy_at(
        trajectory: DailyReferenceTrajectory,
        *,
        at: datetime,
    ) -> float:
        """Return projected stored energy at one canonical interval boundary."""

        interval = next(
            (item for item in trajectory.intervals if item.starts_at <= at < item.ends_at),
            None,
        )
        if interval is not None:
            return interval.storage_energy_at_start_wh
        if at >= trajectory.intervals[-1].ends_at:
            return trajectory.intervals[-1].storage_energy_at_end_wh
        return trajectory.intervals[0].storage_energy_at_start_wh

    @staticmethod
    def _market_routes(
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy,
        opportunities: OpportunitySet,
    ) -> tuple[tuple[MarketCapacityRoute, ...], bool]:
        if not trading_policy.market_routes_enabled:
            return (), False
        if len(snapshot.current_storage_states) != 1:
            return (), False
        storage = snapshot.current_storage_states[0]
        matching_limits = tuple(
            item
            for item in snapshot.storage_physical_limits
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(matching_limits) != 1:
            return (), False
        limits = matching_limits[0]
        if (
            opportunities.snapshot_id != snapshot.snapshot_id
            or opportunities.detection_status != "ready"
        ):
            return (), False

        def opportunity_windows(kind: str) -> tuple[_MarketOpportunityWindow, ...]:
            windows: list[_MarketOpportunityWindow] = []
            for opportunity in opportunities.opportunities:
                if opportunity.kind != kind:
                    continue
                intervals = tuple(
                    interval
                    for interval in tariffs.intervals
                    if interval.starts_at >= opportunity.starts_at
                    and interval.ends_at <= opportunity.ends_at
                    and interval.ends_at > snapshot.captured_at
                )
                if intervals and all(
                    left.ends_at == right.starts_at
                    for left, right in zip(intervals, intervals[1:], strict=False)
                ):
                    windows.append(
                        _MarketOpportunityWindow(
                            opportunity_id=opportunity.opportunity_id,
                            intervals=intervals,
                        )
                    )
            return tuple(windows)

        negative_groups = opportunity_windows(NEGATIVE_PRICE_WINDOW)
        high_windows = opportunity_windows(HIGH_EXPORT_VALUE_WINDOW)

        maximum_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
        minimum_energy_wh = limits.minimum_soc * storage.usable_capacity_wh
        current_energy_wh = storage.current_soc * storage.usable_capacity_wh
        usable_storage_range_wh = maximum_energy_wh - minimum_energy_wh
        # DEV.225 turns the User Rule into one bounded energy hourglass before
        # any market path is built.  The configured percentage is additionally
        # clamped by the physical lower bound, the household unexpected reserve
        # and the explicitly accepted extra reserve.  Full scenario simulation
        # remains authoritative for larger household requirements.
        maximum_safe_trading_fraction = max(
            0.0,
            limits.maximum_soc
            - limits.minimum_soc
            - snapshot.household_unexpected_reserve_fraction
            - trading_policy.additional_reserve_fraction,
        )
        trading_stored_energy_budget_wh = storage.usable_capacity_wh * min(
            trading_policy.maximum_trading_soc_fraction,
            maximum_safe_trading_fraction,
        )
        trading_export_budget_wh = (
            trading_stored_energy_budget_wh * conversion_model.discharge_efficiency
        )
        protected_horizon_end_energy_wh = min(
            maximum_energy_wh,
            minimum_energy_wh
            + storage.usable_capacity_wh
            * (
                snapshot.household_unexpected_reserve_fraction
                + trading_policy.additional_reserve_fraction
            ),
        )
        result: list[MarketCapacityRoute] = []

        for opportunity_window in negative_groups:
            group = opportunity_window.intervals
            starts_at = group[0].starts_at
            ends_at = group[-1].ends_at
            duration_hours = (ends_at - starts_at).total_seconds() / 3600.0
            maximum_charge_input_wh = limits.maximum_charge_input_power_w * duration_hours
            reserved_storage_room_wh = min(
                usable_storage_range_wh,
                maximum_charge_input_wh * conversion_model.charge_efficiency,
                trading_stored_energy_budget_wh,
            )
            maximum_charge_input_wh = reserved_storage_room_wh / conversion_model.charge_efficiency
            ceiling_wh = maximum_energy_wh - reserved_storage_room_wh
            required_stored_discharge_wh = max(0.0, current_energy_wh - ceiling_wh)
            result.append(
                MarketCapacityRoute(
                    route_id=(
                        f"mep-capacity:{snapshot.snapshot_id}:"
                        f"{starts_at.isoformat()}:{ends_at.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    opportunity_ids=(opportunity_window.opportunity_id,),
                    window_starts_at=starts_at,
                    window_ends_at=ends_at,
                    maximum_charge_input_wh=maximum_charge_input_wh,
                    reserved_storage_room_wh=reserved_storage_room_wh,
                    storage_energy_ceiling_before_window_wh=ceiling_wh,
                    required_pre_window_discharge_output_wh=(
                        required_stored_discharge_wh * conversion_model.discharge_efficiency
                    ),
                    opportunity_window_starts_at=starts_at,
                    opportunity_window_ends_at=ends_at,
                    charge_safety_margin_seconds=0.0,
                    reason="negative_all_in_import_window",
                    method_version=METHOD_VERSION,
                )
            )
        # One standalone market decision uses the canonical native plan only to
        # value its future recovery mix. It never creates a charge route of its
        # own: normal PV-first planning remains responsible for PV, mixed or
        # grid-only recovery after the bounded export hourglass is consumed.
        recovery_result = MarketDailyPlanner._representative_recovery_result(native_observation)
        recovery_rate = MarketDailyPlanner._weighted_recovery_rate(
            recovery_result,
            tariffs=tariffs,
        )
        rte = conversion_model.charge_efficiency * conversion_model.discharge_efficiency
        minimum_export_rate = trading_policy.minimum_export_rate(recovery_rate, rte)
        trade_candidates: list[tuple[float, float, MarketCapacityRoute]] = []
        for export_opportunity in high_windows:
            for export_window in _peak_anchored_export_windows(export_opportunity.intervals):
                export_start = export_window[0].starts_at
                export_end = export_window[-1].ends_at
                available_output_wh = min(
                    max(
                        0.0,
                        MarketDailyPlanner._storage_energy_at(
                            trajectory,
                            at=export_start,
                        )
                        - protected_horizon_end_energy_wh,
                    )
                    * conversion_model.discharge_efficiency
                    for trajectory in recovery_result.run.simulation.trajectories
                )
                export_capacity_wh = sum(
                    limits.maximum_discharge_output_power_w * _duration_hours(interval)
                    for interval in export_window
                )
                export_output_wh = min(
                    trading_export_budget_wh,
                    available_output_wh,
                    export_capacity_wh,
                )
                if export_output_wh <= 1e-6:
                    continue
                export_rate = sum(
                    item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                    for item in export_window
                ) / ((export_end - export_start).total_seconds())
                indicated_result = export_output_wh / 1000.0 * (export_rate - minimum_export_rate)
                if (
                    export_rate < minimum_export_rate
                    or indicated_result < trading_policy.minimum_total_route_profit_eur
                ):
                    continue
                trade_candidates.append(
                    (
                        indicated_result,
                        export_output_wh,
                        MarketCapacityRoute(
                            route_id=(
                                f"mep-grid-trade:{snapshot.snapshot_id}:"
                                f"{export_start.isoformat()}:{export_end.isoformat()}"
                            ),
                            snapshot_id=snapshot.snapshot_id,
                            opportunity_ids=(export_opportunity.opportunity_id,),
                            window_starts_at=export_start,
                            window_ends_at=export_end,
                            maximum_charge_input_wh=0.0,
                            reserved_storage_room_wh=0.0,
                            storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                            required_pre_window_discharge_output_wh=export_output_wh,
                            opportunity_window_starts_at=(
                                export_opportunity.intervals[0].starts_at
                            ),
                            opportunity_window_ends_at=(export_opportunity.intervals[-1].ends_at),
                            charge_safety_margin_seconds=0.0,
                            export_window_starts_at=export_start,
                            export_window_ends_at=export_end,
                            route_kind="grid_trade",
                            reason="profitable_available_energy_export_spread",
                            average_export_eur_per_kwh=export_rate,
                            average_recharge_eur_per_kwh=recovery_rate,
                            minimum_export_eur_per_kwh=minimum_export_rate,
                            method_version=METHOD_VERSION,
                        ),
                    )
                )
        if trade_candidates:
            result.append(
                max(
                    trade_candidates,
                    key=lambda item: (
                        item[0],
                        item[1],
                        -item[2].window_starts_at.timestamp(),
                    ),
                )[2]
            )

        return tuple(result), False

    def _assess_routes(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy,
        routes: tuple[MarketCapacityRoute, ...],
        maximum_duration: timedelta,
    ) -> tuple[MarketRouteAssessment, ...]:
        if not routes:
            return ()
        baseline_schedule_id = native_observation.strategy_space.schedules[0].schedule_id
        baseline_result = next(
            item
            for item in native_observation.observer_result.portfolio.strategy_results
            if item.intent_schedule.schedule_id == baseline_schedule_id
        )
        recovery_result = self._representative_recovery_result(native_observation)
        adapter = IndependentDailyReferenceAdapter()
        inputs = adapter.build_inputs(
            snapshot,
            horizon_end=tariffs.horizon_end,
            maximum_duration=maximum_duration,
        )
        assessments: list[MarketRouteAssessment] = []
        for route in routes:
            source_result = (
                baseline_result if route.route_kind == "negative_capacity" else recovery_result
            )
            schedule = self._market_schedule(
                source_result.intent_schedule,
                snapshot=snapshot,
                route=route,
                maximum_discharge_output_power_w=(inputs.maximum_discharge_output_power_w),
                preserve_pv_during_grid_charge=(trading_policy.preserve_pv_during_grid_charge),
            )
            market_result = (
                IndependentDailyReferencePortfolioProducer()
                .produce(
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
                    maximum_discharge_output_power_w=(inputs.maximum_discharge_output_power_w),
                )
                .strategy_results[0]
            )
            assessments.append(
                self._assessment(
                    route=route,
                    parent_result=source_result,
                    market_result=market_result,
                    assessed_schedule=schedule,
                    wear_eur_per_export_kwh=trading_policy.wear_eur_per_export_kwh,
                    minimum_total_route_profit_eur=(trading_policy.minimum_total_route_profit_eur),
                )
            )
        return tuple(assessments)

    @staticmethod
    def _market_schedule(
        baseline: DailyReferenceIntentSchedule,
        *,
        snapshot: PlanningInputSnapshot,
        route: MarketCapacityRoute,
        maximum_discharge_output_power_w: float,
        preserve_pv_during_grid_charge: bool,
    ) -> DailyReferenceIntentSchedule:
        export_targets: dict[tuple[datetime, datetime], float] = {}
        explicit_export_requests = (
            (
                (
                    route.export_window_starts_at,
                    route.export_window_ends_at,
                    route.required_pre_window_discharge_output_wh,
                ),
            )
            if route.export_window_starts_at is not None and route.export_window_ends_at is not None
            else ()
        )
        if explicit_export_requests:
            for export_start, export_end, requested_output_wh in explicit_export_requests:
                remaining_output_wh = requested_output_wh
                candidate_intervals = tuple(
                    interval
                    for interval in baseline.intervals
                    if interval.starts_at < export_end and interval.ends_at > export_start
                )
                for interval in candidate_intervals:
                    if remaining_output_wh <= 0.0:
                        break
                    duration_hours = (
                        interval.ends_at - interval.starts_at
                    ).total_seconds() / 3600.0
                    target_wh = min(
                        remaining_output_wh,
                        maximum_discharge_output_power_w * duration_hours,
                    )
                    export_targets[(interval.starts_at, interval.ends_at)] = target_wh
                    remaining_output_wh -= target_wh
        else:
            remaining_output_wh = route.required_pre_window_discharge_output_wh
            for interval in reversed(baseline.intervals):
                if interval.ends_at > route.window_starts_at:
                    continue
                if remaining_output_wh <= 0.0:
                    break
                duration_hours = (interval.ends_at - interval.starts_at).total_seconds() / 3600.0
                target_wh = min(
                    remaining_output_wh,
                    maximum_discharge_output_power_w * duration_hours,
                )
                export_targets[(interval.starts_at, interval.ends_at)] = target_wh
                remaining_output_wh -= target_wh
        schedule_id = f"mep-market:{route.route_id}:{baseline.schedule_id}"
        intervals_list: list[DailyReferenceIntentInterval] = []
        for item in baseline.intervals:
            inside_explicit_charge = (
                route.route_kind == "negative_capacity"
                and route.maximum_charge_input_wh > 0.0
                and item.starts_at < route.window_ends_at
                and item.ends_at > route.window_starts_at
            )
            inside_projected_pv = (
                preserve_pv_during_grid_charge
                and route.maximum_charge_input_wh > 0.0
                and MarketDailyPlanner._has_possible_pv(
                    snapshot,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                )
            )
            if inside_explicit_charge:
                intent = DailyStorageIntent.GRID_REQUIREMENT
            elif (item.starts_at, item.ends_at) in export_targets:
                intent = DailyStorageIntent.STORAGE_EXPORT
            elif inside_projected_pv:
                intent = DailyStorageIntent.NOM
            else:
                # The standalone trade overlays exactly one export hourglass.
                # PV, mixed and grid-only recovery stay owned by the canonical
                # native schedule and are never reconstructed here.
                intent = item.intent
            intervals_list.append(
                DailyReferenceIntentInterval(
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                    intent=intent,
                    storage_export_target_wh=(
                        export_targets.get((item.starts_at, item.ends_at), 0.0)
                        if intent is DailyStorageIntent.STORAGE_EXPORT
                        else 0.0
                    ),
                )
            )
        intervals = tuple(intervals_list)
        return DailyReferenceIntentSchedule(
            schedule_id=schedule_id,
            snapshot_id=baseline.snapshot_id,
            horizon_start=baseline.horizon_start,
            horizon_end=baseline.horizon_end,
            intervals=intervals,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _has_possible_pv(
        snapshot: PlanningInputSnapshot,
        *,
        starts_at: datetime,
        ends_at: datetime,
    ) -> bool:
        timeline = snapshot.pv_energy_timeline
        if timeline is None:
            return True
        overlapping = tuple(
            interval
            for interval in timeline.intervals
            if interval.starts_at < ends_at and interval.ends_at > starts_at
        )
        if not overlapping:
            return True
        return any(
            (
                interval.forecast_upper_energy_wh
                if interval.forecast_upper_energy_wh is not None
                else interval.pv_energy_wh
            )
            > 1e-6
            for interval in overlapping
        )

    @staticmethod
    def _assessment(
        *,
        route: MarketCapacityRoute,
        parent_result: DailyReferenceStrategyResult,
        market_result: DailyReferenceStrategyResult,
        assessed_schedule: DailyReferenceIntentSchedule | None = None,
        wear_eur_per_export_kwh: float,
        minimum_total_route_profit_eur: float,
    ) -> MarketRouteAssessment:
        baseline_run = parent_result.run
        market_run = market_result.run
        baseline_assessment = {item.scenario: item for item in baseline_run.assessment.assessments}
        market_assessment = {item.scenario: item for item in market_run.assessment.assessments}
        baseline_financial = {item.scenario: item for item in baseline_run.financial.paths}
        market_financial = {item.scenario: item for item in market_run.financial.paths}
        incremental_results: list[float] = []
        result_per_export_kwh: list[float] = []
        wear_values: list[float] = []
        scenario_evidence: list[MarketRouteScenarioEvidence] = []
        market_trajectories = {item.scenario: item for item in market_run.simulation.trajectories}
        schedule = assessed_schedule or market_result.intent_schedule
        explicit_charge_intervals = {
            (item.starts_at, item.ends_at)
            for item in schedule.intervals
            if item.intent is DailyStorageIntent.GRID_REQUIREMENT
        }
        for scenario in PVScenario:
            baseline_flow = baseline_assessment[scenario]
            market_flow = market_assessment[scenario]
            extra_export_kwh = (
                max(
                    0.0,
                    market_flow.storage_to_grid_output_wh - baseline_flow.storage_to_grid_output_wh,
                )
                / 1000.0
            )
            wear_eur = extra_export_kwh * wear_eur_per_export_kwh
            incremental_eur = (
                market_financial[scenario].net_financial_result_eur
                - baseline_financial[scenario].net_financial_result_eur
                - wear_eur
            )
            incremental_results.append(incremental_eur)
            wear_values.append(wear_eur)
            result_per_export_kwh.append(
                incremental_eur / extra_export_kwh if extra_export_kwh > 0.0 else float("-inf")
            )
            trajectory = market_trajectories[scenario]
            scenario_evidence.append(
                MarketRouteScenarioEvidence(
                    scenario=scenario,
                    physically_complete=market_flow.physically_complete,
                    reserve_respected=market_flow.reserve_respected,
                    target_reached_during_horizon=(market_flow.target_reached_during_horizon),
                    target_held_at_horizon_end=(market_flow.target_held_at_horizon_end),
                    target_storage_energy_wh=trajectory.target_storage_energy_wh,
                    minimum_storage_energy_wh=trajectory.minimum_storage_energy_wh,
                    minimum_storage_energy_observed_wh=(
                        market_flow.minimum_storage_energy_observed_wh
                    ),
                    storage_energy_at_horizon_end_wh=(market_flow.storage_energy_at_horizon_end_wh),
                    baseline_storage_energy_at_horizon_end_wh=(
                        baseline_flow.storage_energy_at_horizon_end_wh
                    ),
                    target_shortfall_wh=max(
                        0.0,
                        trajectory.target_storage_energy_wh
                        - market_flow.storage_energy_at_horizon_end_wh,
                    ),
                    reserve_margin_wh=(
                        market_flow.minimum_storage_energy_observed_wh
                        - trajectory.minimum_storage_energy_wh
                    ),
                    grid_to_storage_input_wh=sum(
                        interval.grid_to_storage_input_wh for interval in trajectory.intervals
                    ),
                    explicit_charge_pv_to_storage_input_wh=sum(
                        interval.pv_to_storage_input_wh
                        for interval in trajectory.intervals
                        if (interval.starts_at, interval.ends_at) in explicit_charge_intervals
                    ),
                    explicit_charge_grid_to_storage_input_wh=sum(
                        interval.grid_to_storage_input_wh
                        for interval in trajectory.intervals
                        if (interval.starts_at, interval.ends_at) in explicit_charge_intervals
                    ),
                    household_demand_wh=market_flow.household_demand_wh,
                    incremental_financial_result_eur=incremental_eur,
                    exported_energy_kwh=extra_export_kwh,
                    storage_energy_checkpoints=tuple(
                        MarketRouteStorageCheckpoint(
                            at=interval.ends_at,
                            energy_wh=interval.storage_energy_at_end_wh,
                        )
                        for interval in trajectory.intervals
                    ),
                    self_consumed_pv_wh=sum(
                        interval.pv_to_household_wh + interval.pv_to_storage_input_wh
                        for interval in trajectory.intervals
                    ),
                    grid_to_household_wh=sum(
                        interval.grid_to_household_wh for interval in trajectory.intervals
                    ),
                    conversion_losses_wh=sum(
                        interval.storage_charge_loss_wh + interval.storage_discharge_loss_wh
                        for interval in trajectory.intervals
                    ),
                    minimum_confidence=min(
                        interval.confidence for interval in trajectory.intervals
                    ),
                    total_financial_result_eur=(
                        market_financial[scenario].net_financial_result_eur - wear_eur
                    ),
                )
            )
        physically_admissible = all(
            item.physically_complete
            and item.reserve_respected
            and (
                route.route_kind == "grid_trade"
                or item.storage_energy_at_horizon_end_wh + 1e-6
                >= baseline_assessment[scenario].storage_energy_at_horizon_end_wh
            )
            for scenario, item in market_assessment.items()
        )
        worst_result = min(incremental_results)
        minimum_per_export = min(result_per_export_kwh)
        admitted = (
            physically_admissible
            and worst_result >= minimum_total_route_profit_eur
            and minimum_per_export > 0.0
        )
        return MarketRouteAssessment(
            route_id=route.route_id,
            source_native_schedule_id=parent_result.intent_schedule.schedule_id,
            market_schedule_id=schedule.schedule_id,
            intent_schedule=schedule,
            physically_admissible=physically_admissible,
            incremental_wear_eur=max(wear_values),
            worst_case_incremental_result_eur=worst_result,
            minimum_incremental_result_eur_per_exported_kwh=minimum_per_export,
            admitted=admitted,
            admission_reason=(
                "admitted_profitable_complete_route"
                if admitted
                else (
                    "physical_path_or_reserve_invalid"
                    if not physically_admissible
                    else "minimum_total_route_profit_not_met"
                )
            ),
            scenario_evidence=tuple(scenario_evidence),
            method_version=METHOD_VERSION,
            minimum_total_route_profit_eur=minimum_total_route_profit_eur,
        )
