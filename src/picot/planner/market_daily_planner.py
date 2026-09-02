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
from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.domain.storage_energy_inventory import (
    StorageEnergyCostAllocation,
    StorageEnergyInventory,
)
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
METHOD_VERSION = "market-daily-planner:v10"
MARKET_DAILY_MAXIMUM_DURATION = timedelta(hours=36)


def _household_energy_requirement_deadline(
    observation: DailyReferenceStrategyObservation,
) -> datetime:
    """Return the first physically reachable household-storage deadline.

    ADR-017 and ADR-037 make the projected household energy balance authoritative
    for when stored energy is needed.  This is MEP-native physical evidence; it
    is not a CP deadline and it does not select a charging window.
    """

    baseline = next(
        item
        for item in observation.observer_result.portfolio.strategy_results
        if all(
            interval.intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
            for interval in item.intent_schedule.intervals
        )
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
                and interval.intent
                in {DailyStorageIntent.NOM, DailyStorageIntent.GRID_REQUIREMENT}
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
    inventory_deliverable_energy_wh: float | None = None
    inventory_acquisition_cost_eur: float | None = None
    inventory_sources: tuple[str, ...] = ()

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
            "pv_trade",
            "pv_trade_grid_recovery",
            "stored_energy_export",
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
        if self.inventory_deliverable_energy_wh is not None and (
            self.inventory_deliverable_energy_wh < 0.0
            or self.inventory_acquisition_cost_eur is None
        ):
            raise ValueError("MEP inventory valuation must be complete.")


@dataclass(frozen=True, slots=True)
class _MarketOpportunityWindow:
    opportunity_id: str
    intervals: tuple[DailyReferenceTariffInterval, ...]


def _duration_hours(interval: DailyReferenceTariffInterval) -> float:
    return (interval.ends_at - interval.starts_at).total_seconds() / 3600.0


def _average_import_rate(
    intervals: tuple[DailyReferenceTariffInterval, ...],
) -> float:
    seconds = sum((item.ends_at - item.starts_at).total_seconds() for item in intervals)
    return (
        sum(
            item.import_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
            for item in intervals
        )
        / seconds
    )


def _minimal_charge_subwindows(
    intervals: tuple[DailyReferenceTariffInterval, ...],
    *,
    required_charge_input_wh: float,
    maximum_charge_input_power_w: float,
) -> tuple[tuple[DailyReferenceTariffInterval, ...], ...]:
    """Return one interval-minimal charge window for every feasible start.

    The containing price Opportunity remains unchanged.  Candidate construction
    branches only on canonical source intervals and keeps one trailing interval
    as execution margin when the Opportunity has enough spare duration.
    """

    if required_charge_input_wh <= 0.0 or maximum_charge_input_power_w <= 0.0:
        return ()
    candidates: list[tuple[DailyReferenceTariffInterval, ...]] = []
    for start_index in range(len(intervals)):
        capacity_wh = 0.0
        selected: list[DailyReferenceTariffInterval] = []
        for interval in intervals[start_index:]:
            if selected and selected[-1].ends_at != interval.starts_at:
                break
            selected.append(interval)
            capacity_wh += maximum_charge_input_power_w * _duration_hours(interval)
            if capacity_wh + 1e-6 >= required_charge_input_wh:
                candidates.append(tuple(selected))
                break
    if not candidates:
        return ()

    opportunity_end = intervals[-1].ends_at
    safety_duration = intervals[-1].ends_at - intervals[-1].starts_at
    with_safety_margin = tuple(
        candidate
        for candidate in candidates
        if candidate[-1].ends_at <= opportunity_end - safety_duration
    )
    return with_safety_margin or tuple(candidates)


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
            preserve_pv_during_grid_charge=(
                trading_policy.preserve_pv_during_grid_charge
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
                preserve_pv_during_grid_charge=(
                    trading_policy.preserve_pv_during_grid_charge
                ),
            )
        native_plan_ms = (perf_counter() - phase_started) * 1000.0
        horizon_end = native_observation.strategy_space.schedules[0].horizon_end
        phase_started = perf_counter()
        tariffs = IndependentDailyTariffAdapter().build(
            snapshot,
            horizon_end=horizon_end,
        )
        tariff_build_ms = (perf_counter() - phase_started) * 1000.0
        phase_started = perf_counter()
        routes, recovery_outside_horizon = self._market_routes(
            snapshot=snapshot,
            native_observation=native_observation,
            tariffs=tariffs,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            storage_inventory=storage_inventory,
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
            preserve_pv_during_grid_charge=(
                trading_policy.preserve_pv_during_grid_charge
            ),
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
    def _market_routes(
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy,
        storage_inventory: StorageEnergyInventory | None,
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
        low_windows = opportunity_windows(LOWEST_PRICE_WINDOW)
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
        baseline_schedule_id = native_observation.strategy_space.schedules[0].schedule_id
        baseline_result = next(
            item
            for item in native_observation.observer_result.portfolio.strategy_results
            if item.intent_schedule.schedule_id == baseline_schedule_id
        )
        baseline_lower = next(
            item
            for item in baseline_result.run.simulation.trajectories
            if item.scenario is PVScenario.LOWER
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
        household_path_surplus_output_wh = max(
            0.0,
            (
                baseline_lower.intervals[-1].storage_energy_at_end_wh
                - protected_horizon_end_energy_wh
            )
            * conversion_model.discharge_efficiency,
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
            maximum_charge_input_wh = (
                reserved_storage_room_wh / conversion_model.charge_efficiency
            )
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
        # Ordinary grid trading is a complete charge-then-export route.  It is
        # deliberately generated from MEP's own tariffs, never from an EP
        # candidate or winner.  Full physical simulation and incremental
        # settlement below remain the admission authority.
        trade_candidates: list[
            tuple[
                float,
                _MarketOpportunityWindow,
                tuple[DailyReferenceTariffInterval, ...],
                _MarketOpportunityWindow,
                float,
                float,
            ]
        ] = []
        for charge_opportunity in low_windows:
            opportunity_charge_window = charge_opportunity.intervals
            opportunity_charge_hours = sum(
                _duration_hours(item) for item in opportunity_charge_window
            )
            for export_opportunity in high_windows:
                export_windows = _peak_anchored_export_windows(export_opportunity.intervals)
                export_window = next(
                    (
                        window
                        for window in export_windows
                        if sum(
                            limits.maximum_discharge_output_power_w
                            * _duration_hours(interval)
                            for interval in window
                        )
                        + 1e-6
                        >= trading_export_budget_wh
                    ),
                    export_windows[-1] if export_windows else (),
                )
                if not export_window:
                    continue
                bounded_export_opportunity = _MarketOpportunityWindow(
                    opportunity_id=export_opportunity.opportunity_id,
                    intervals=export_window,
                )
                export_start = export_window[0].starts_at
                export_end = export_window[-1].ends_at
                export_hours = (export_end - export_start).total_seconds() / 3600
                charge_input_wh = min(
                    usable_storage_range_wh / conversion_model.charge_efficiency,
                    trading_stored_energy_budget_wh / conversion_model.charge_efficiency,
                    limits.maximum_charge_input_power_w * opportunity_charge_hours,
                    limits.maximum_discharge_output_power_w
                    * export_hours
                    / (conversion_model.charge_efficiency * conversion_model.discharge_efficiency),
                )
                export_output_wh = (
                    charge_input_wh
                    * conversion_model.charge_efficiency
                    * conversion_model.discharge_efficiency
                )
                charge_subwindows = _minimal_charge_subwindows(
                    opportunity_charge_window,
                    required_charge_input_wh=charge_input_wh,
                    maximum_charge_input_power_w=(limits.maximum_charge_input_power_w),
                )
                if charge_subwindows:
                    charge_subwindows = (
                        min(
                            charge_subwindows,
                            key=lambda window: (
                                _average_import_rate(window),
                                -window[0].starts_at.timestamp(),
                            ),
                        ),
                    )
                export_rate = sum(
                    item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                    for item in export_window
                ) / ((export_end - export_start).total_seconds())
                for charge_window in charge_subwindows:
                    charge_start = charge_window[0].starts_at
                    charge_end = charge_window[-1].ends_at
                    if export_start < charge_end:
                        continue
                    charge_rate = _average_import_rate(charge_window)
                    indicated_result = (
                        export_output_wh / 1000 * export_rate
                        - charge_input_wh / 1000 * charge_rate
                        - export_output_wh / 1000 * trading_policy.wear_eur_per_export_kwh
                    )
                    trade_candidates.append(
                        (
                            indicated_result,
                            charge_opportunity,
                            charge_window,
                            bounded_export_opportunity,
                            charge_input_wh,
                            export_output_wh,
                        )
                    )
        # One energy hourglass is projected on one best charge/export pair.
        # Alternative starts inside the same price valleys are not different
        # Energy Paths; rolling replanning may move this single window later.
        for (
            _indicated_result,
            charge_opportunity,
            charge_window,
            export_opportunity,
            charge_input_wh,
            export_output_wh,
        ) in sorted(
            trade_candidates,
            key=lambda item: item[0],
            reverse=True,
        )[:1]:
            export_window = export_opportunity.intervals
            charge_start = charge_window[0].starts_at
            charge_end = charge_window[-1].ends_at
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
            charge_rate = _average_import_rate(charge_window)
            export_rate = sum(
                item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                for item in export_window
            ) / ((export_end - export_start).total_seconds())
            minimum_export_rate = trading_policy.minimum_export_rate(
                charge_rate,
                conversion_model.charge_efficiency * conversion_model.discharge_efficiency,
            )
            if export_rate < minimum_export_rate:
                continue
            result.append(
                MarketCapacityRoute(
                    route_id=(
                        f"mep-grid-trade:{snapshot.snapshot_id}:"
                        f"{charge_start.isoformat()}:{charge_end.isoformat()}:"
                        f"{export_start.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    opportunity_ids=(
                        charge_opportunity.opportunity_id,
                        export_opportunity.opportunity_id,
                    ),
                    window_starts_at=charge_start,
                    window_ends_at=charge_end,
                    maximum_charge_input_wh=charge_input_wh,
                    reserved_storage_room_wh=(charge_input_wh * conversion_model.charge_efficiency),
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
                    opportunity_window_starts_at=(charge_opportunity.intervals[0].starts_at),
                    opportunity_window_ends_at=(charge_opportunity.intervals[-1].ends_at),
                    charge_safety_margin_seconds=(
                        charge_opportunity.intervals[-1].ends_at - charge_end
                    ).total_seconds(),
                    export_window_starts_at=export_start,
                    export_window_ends_at=export_end,
                    route_kind="grid_trade",
                    reason="profitable_grid_charge_export_spread",
                    average_export_eur_per_kwh=export_rate,
                    average_recharge_eur_per_kwh=charge_rate,
                    minimum_export_eur_per_kwh=minimum_export_rate,
                    method_version=METHOD_VERSION,
                )
            )

        # Energy already present above the protected reserve may be exported
        # without inventing a linked acquisition or forcing restoration to the
        # baseline horizon-end target.  Candidate sizes grow from the absolute
        # export-price peak so every possible vendor window retains that peak.
        free_stored_output_wh = max(
            0.0,
            (current_energy_wh - minimum_energy_wh) * conversion_model.discharge_efficiency,
        )
        free_stored_output_wh = min(
            free_stored_output_wh,
            trading_export_budget_wh,
            household_path_surplus_output_wh,
        )
        fallback_acquisition_rate = min(
            (item.import_eur_per_kwh for window in low_windows for item in window.intervals),
            default=0.0,
        )
        for export_opportunity in high_windows:
            export_windows = _peak_anchored_export_windows(export_opportunity.intervals)
            bounded_export_window = next(
                (
                    window
                    for window in export_windows
                    if sum(
                        limits.maximum_discharge_output_power_w * _duration_hours(interval)
                        for interval in window
                    )
                    + 1e-6
                    >= free_stored_output_wh
                ),
                export_windows[-1] if export_windows else (),
            )
            for export_window in ((bounded_export_window,) if bounded_export_window else ()):
                export_start = export_window[0].starts_at
                export_end = export_window[-1].ends_at
                export_capacity_wh = sum(
                    limits.maximum_discharge_output_power_w * _duration_hours(interval)
                    for interval in export_window
                )
                export_output_wh = min(
                    free_stored_output_wh,
                    export_capacity_wh,
                )
                inventory_allocation = None
                if storage_inventory is not None:
                    if (
                        storage_inventory.execution_scope_id != storage.execution_scope_id
                        or storage_inventory.captured_at > snapshot.captured_at
                    ):
                        continue
                    inventory_allocation = storage_inventory.cheapest_known_allocation(
                        maximum_deliverable_energy_wh=export_output_wh,
                        discharge_efficiency=conversion_model.discharge_efficiency,
                    )
                    export_output_wh = inventory_allocation.deliverable_energy_wh
                if export_output_wh <= 0.0:
                    continue
                export_rate = sum(
                    item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                    for item in export_window
                ) / ((export_end - export_start).total_seconds())
                if inventory_allocation is not None:
                    acquisition_rate = inventory_allocation.acquisition_cost_eur / (
                        inventory_allocation.deliverable_energy_wh / 1000.0
                    )
                    minimum_export_rate = (
                        acquisition_rate * (1.0 + trading_policy.margin_fraction)
                        + trading_policy.wear_eur_per_export_kwh
                    )
                else:
                    minimum_export_rate = trading_policy.minimum_export_rate(
                        fallback_acquisition_rate,
                        conversion_model.charge_efficiency * conversion_model.discharge_efficiency,
                    )
                if export_rate < minimum_export_rate:
                    continue
                result.append(
                    MarketCapacityRoute(
                        route_id=(
                            f"mep-stored-energy-export:{snapshot.snapshot_id}:"
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
                        opportunity_window_starts_at=(export_opportunity.intervals[0].starts_at),
                        opportunity_window_ends_at=(export_opportunity.intervals[-1].ends_at),
                        charge_safety_margin_seconds=0.0,
                        export_window_starts_at=export_start,
                        export_window_ends_at=export_end,
                        route_kind="stored_energy_export",
                        reason="profitable_export_from_protected_stored_energy",
                        average_export_eur_per_kwh=export_rate,
                        average_recharge_eur_per_kwh=None,
                        minimum_export_eur_per_kwh=minimum_export_rate,
                        inventory_deliverable_energy_wh=(
                            inventory_allocation.deliverable_energy_wh
                            if inventory_allocation is not None
                            else None
                        ),
                        inventory_acquisition_cost_eur=(
                            inventory_allocation.acquisition_cost_eur
                            if inventory_allocation is not None
                            else None
                        ),
                        inventory_sources=(
                            inventory_allocation.sources if inventory_allocation is not None else ()
                        ),
                        method_version=METHOD_VERSION,
                    )
                )
        # PV trade candidates do not invent an acquisition price.  They retain
        # MEP's own PV/NOM schedule and only test whether demonstrably surplus
        # stored energy can be exported in a high-value interval while the
        # target and reserve remain protected in every PV scenario.
        pv_trade_candidates: list[
            tuple[
                float,
                _MarketOpportunityWindow,
                _MarketOpportunityWindow,
                float,
                float,
                StorageEnergyCostAllocation | None,
            ]
        ] = []
        rte = conversion_model.charge_efficiency * conversion_model.discharge_efficiency
        recovery_outside_horizon = False
        cheapest_known_recharge_rate = min(
            (item.import_eur_per_kwh for window in low_windows for item in window.intervals),
            default=0.0,
        )
        for export_opportunity in high_windows:
            export_windows = _peak_anchored_export_windows(export_opportunity.intervals)
            export_window = next(
                (
                    window
                    for window in export_windows
                    if sum(
                        limits.maximum_discharge_output_power_w * _duration_hours(interval)
                        for interval in window
                    )
                    + 1e-6
                    >= trading_export_budget_wh
                ),
                export_windows[-1] if export_windows else (),
            )
            if not export_window:
                continue
            export_opportunity = _MarketOpportunityWindow(
                opportunity_id=export_opportunity.opportunity_id,
                intervals=export_window,
            )
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
            export_hours = (export_end - export_start).total_seconds() / 3600
            export_output_wh = min(
                usable_storage_range_wh,
                trading_export_budget_wh,
                limits.maximum_discharge_output_power_w * export_hours,
            )
            inventory_allocation = None
            if storage_inventory is not None:
                if (
                    storage_inventory.execution_scope_id != storage.execution_scope_id
                    or storage_inventory.captured_at > snapshot.captured_at
                ):
                    continue
                inventory_allocation = storage_inventory.cheapest_known_allocation(
                    maximum_deliverable_energy_wh=export_output_wh,
                    discharge_efficiency=conversion_model.discharge_efficiency,
                )
                export_output_wh = inventory_allocation.deliverable_energy_wh
            if export_output_wh <= 0.0:
                continue
            export_rate = sum(
                item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                for item in export_window
            ) / ((export_end - export_start).total_seconds())
            required_recharge_input_wh = export_output_wh / rte
            recovery_windows: list[_MarketOpportunityWindow] = []
            for recovery_opportunity in low_windows:
                recovery_window = recovery_opportunity.intervals
                if recovery_window[0].starts_at < export_end:
                    continue
                available_input_wh = sum(
                    limits.maximum_charge_input_power_w
                    * (interval.ends_at - interval.starts_at).total_seconds()
                    / 3600.0
                    for interval in recovery_window
                )
                if available_input_wh >= required_recharge_input_wh:
                    recovery_windows.append(recovery_opportunity)
            recovery_candidates = []
            for recovery_opportunity in recovery_windows:
                recovery_window = recovery_opportunity.intervals
                recovery_start = recovery_window[0].starts_at
                recovery_end = recovery_window[-1].ends_at
                recovery_hours = (recovery_end - recovery_start).total_seconds() / 3600
                if (
                    limits.maximum_charge_input_power_w * recovery_hours
                    < required_recharge_input_wh
                ):
                    continue
                recharge_rate = sum(
                    item.import_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                    for item in recovery_window
                ) / ((recovery_end - recovery_start).total_seconds())
                recovery_candidates.append((recharge_rate, recovery_opportunity))
            if not recovery_candidates:
                if export_rate >= trading_policy.minimum_export_rate(
                    cheapest_known_recharge_rate,
                    rte,
                ):
                    recovery_outside_horizon = True
                continue
            lowest_recharge_rate = min(item[0] for item in recovery_candidates)
            recharge_rate, recovery_opportunity = max(
                (item for item in recovery_candidates if item[0] == lowest_recharge_rate),
                key=lambda item: item[1].intervals[0].starts_at,
            )
            recovery_window = recovery_opportunity.intervals
            minimum_export_rate = trading_policy.minimum_export_rate(recharge_rate, rte)
            if inventory_allocation is not None:
                inventory_rate = inventory_allocation.acquisition_cost_eur / (
                    inventory_allocation.deliverable_energy_wh / 1000.0
                )
                inventory_minimum_export_rate = (
                    inventory_rate * (1.0 + trading_policy.margin_fraction)
                    + trading_policy.wear_eur_per_export_kwh
                )
            else:
                inventory_minimum_export_rate = minimum_export_rate
            if export_rate < inventory_minimum_export_rate:
                continue
            pv_trade_candidates.append(
                (
                    export_rate - inventory_minimum_export_rate,
                    export_opportunity,
                    recovery_opportunity,
                    export_output_wh,
                    minimum_export_rate,
                    inventory_allocation,
                )
            )
        for (
            _,
            export_opportunity,
            recovery_opportunity,
            export_output_wh,
            minimum_export_rate,
            inventory_allocation,
        ) in sorted(
            pv_trade_candidates,
            key=lambda item: (item[0], item[3]),
            reverse=True,
        )[:1]:
            export_window = export_opportunity.intervals
            recovery_window = recovery_opportunity.intervals
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
            recovery_start = recovery_window[0].starts_at
            recovery_end = recovery_window[-1].ends_at
            export_rate = sum(
                item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                for item in export_window
            ) / ((export_end - export_start).total_seconds())
            recharge_rate = sum(
                item.import_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                for item in recovery_window
            ) / ((recovery_end - recovery_start).total_seconds())
            recharge_input_wh = export_output_wh / rte
            inventory_deliverable_energy_wh = (
                inventory_allocation.deliverable_energy_wh
                if inventory_allocation is not None
                else None
            )
            inventory_acquisition_cost_eur = (
                inventory_allocation.acquisition_cost_eur
                if inventory_allocation is not None
                else None
            )
            inventory_sources = (
                inventory_allocation.sources if inventory_allocation is not None else ()
            )
            # First assess whether MEP's native PV/NOM schedule restores the
            # sold energy without buying it back.  The cheapest next-day grid
            # price is still the policy reference: it is the proven fallback
            # cost if PV is insufficient.
            result.append(
                MarketCapacityRoute(
                    route_id=(
                        f"mep-pv-trade:{snapshot.snapshot_id}:{export_start.isoformat()}:"
                        f"{export_end.isoformat()}:{recovery_start.isoformat()}:"
                        f"{recovery_end.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    opportunity_ids=(
                        export_opportunity.opportunity_id,
                        recovery_opportunity.opportunity_id,
                    ),
                    window_starts_at=recovery_start,
                    window_ends_at=recovery_end,
                    maximum_charge_input_wh=0.0,
                    reserved_storage_room_wh=0.0,
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
                    opportunity_window_starts_at=recovery_start,
                    opportunity_window_ends_at=recovery_end,
                    charge_safety_margin_seconds=0.0,
                    export_window_starts_at=export_start,
                    export_window_ends_at=export_end,
                    route_kind="pv_trade",
                    reason="export_then_restore_from_planned_pv",
                    average_export_eur_per_kwh=export_rate,
                    average_recharge_eur_per_kwh=recharge_rate,
                    minimum_export_eur_per_kwh=minimum_export_rate,
                    inventory_deliverable_energy_wh=inventory_deliverable_energy_wh,
                    inventory_acquisition_cost_eur=inventory_acquisition_cost_eur,
                    inventory_sources=inventory_sources,
                    method_version=METHOD_VERSION,
                )
            )
            # If PV cannot restore the full traded portion plus household
            # consumption, assess the same export with every interval-minimal
            # explicit-power subwindow inside the selected recovery Opportunity.
            grid_recovery_windows = _minimal_charge_subwindows(
                recovery_window,
                required_charge_input_wh=recharge_input_wh,
                maximum_charge_input_power_w=(limits.maximum_charge_input_power_w),
            )
            if grid_recovery_windows:
                grid_recovery_windows = (
                    min(
                        grid_recovery_windows,
                        key=lambda window: (
                            _average_import_rate(window),
                            -window[0].starts_at.timestamp(),
                        ),
                    ),
                )
            for grid_recovery_window in grid_recovery_windows:
                grid_recovery_start = grid_recovery_window[0].starts_at
                grid_recovery_end = grid_recovery_window[-1].ends_at
                grid_recharge_rate = _average_import_rate(grid_recovery_window)
                grid_minimum_export_rate = trading_policy.minimum_export_rate(
                    grid_recharge_rate,
                    rte,
                )
                if export_rate < grid_minimum_export_rate:
                    continue
                result.append(
                    MarketCapacityRoute(
                        route_id=(
                            f"mep-pv-trade-grid-recovery:{snapshot.snapshot_id}:"
                            f"{export_start.isoformat()}:{export_end.isoformat()}:"
                            f"{grid_recovery_start.isoformat()}:"
                            f"{grid_recovery_end.isoformat()}"
                        ),
                        snapshot_id=snapshot.snapshot_id,
                        opportunity_ids=(
                            export_opportunity.opportunity_id,
                            recovery_opportunity.opportunity_id,
                        ),
                        window_starts_at=grid_recovery_start,
                        window_ends_at=grid_recovery_end,
                        maximum_charge_input_wh=recharge_input_wh,
                        reserved_storage_room_wh=(
                            recharge_input_wh * conversion_model.charge_efficiency
                        ),
                        storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                        required_pre_window_discharge_output_wh=export_output_wh,
                        opportunity_window_starts_at=recovery_start,
                        opportunity_window_ends_at=recovery_end,
                        charge_safety_margin_seconds=(
                            recovery_end - grid_recovery_end
                        ).total_seconds(),
                        export_window_starts_at=export_start,
                        export_window_ends_at=export_end,
                        route_kind="pv_trade_grid_recovery",
                        reason=("export_then_restore_from_pv_preserving_grid_subwindow"),
                        average_export_eur_per_kwh=export_rate,
                        average_recharge_eur_per_kwh=grid_recharge_rate,
                        minimum_export_eur_per_kwh=grid_minimum_export_rate,
                        inventory_deliverable_energy_wh=(inventory_deliverable_energy_wh),
                        inventory_acquisition_cost_eur=(inventory_acquisition_cost_eur),
                        inventory_sources=inventory_sources,
                        method_version=METHOD_VERSION,
                    )
                )
        # Stable de-duplication: the same cheapest/highest pair can be reached
        # through overlapping rankings, but it must be simulated only once.
        return tuple({item.route_id: item for item in result}.values()), recovery_outside_horizon

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
        results = {
            item.intent_schedule.schedule_id: item
            for item in native_observation.observer_result.portfolio.strategy_results
        }
        baseline_schedule_id = native_observation.strategy_space.schedules[0].schedule_id
        baseline_result = results[baseline_schedule_id]
        native_candidates = {
            item.intent_schedule_id: item
            for item in native_observation.observer_result.candidate_set.candidates
        }
        hybrid_candidates = tuple(
            item
            for schedule_id, item in native_candidates.items()
            if "hybrid-pv-grid" in schedule_id
            and item.average_charge_window_price_eur_per_kwh is not None
        )
        hybrid_schedule_ids = {item.intent_schedule_id for item in hybrid_candidates}
        hybrid_results = tuple(
            result
            for result in results.values()
            if result.intent_schedule.schedule_id != baseline_schedule_id
            and result.intent_schedule.schedule_id in hybrid_schedule_ids
            and {
                interval.intent for interval in result.intent_schedule.intervals
            }.issuperset(
                {
                    DailyStorageIntent.NOM,
                    DailyStorageIntent.GRID_REQUIREMENT,
                }
            )
        )
        adapter = IndependentDailyReferenceAdapter()
        inputs = adapter.build_inputs(
            snapshot,
            horizon_end=tariffs.horizon_end,
            maximum_duration=maximum_duration,
        )

        def representative_hybrid_parents(
            route: MarketCapacityRoute,
        ) -> tuple[DailyReferenceStrategyResult, ...]:
            """Retain one non-dominated hybrid for each route timing role."""

            representatives: dict[
                str,
                tuple[tuple[float, float], DailyReferenceStrategyResult],
            ] = {}
            export_start = route.export_window_starts_at or route.window_starts_at
            export_end = route.export_window_ends_at or route.window_ends_at
            for result in hybrid_results:
                grid = tuple(
                    interval
                    for interval in result.intent_schedule.intervals
                    if interval.intent is DailyStorageIntent.GRID_REQUIREMENT
                )
                if not grid:
                    continue
                grid_start = grid[0].starts_at
                grid_end = grid[-1].ends_at
                role = (
                    "before_export"
                    if grid_end <= export_start
                    else "after_export"
                    if grid_start >= export_end
                    else "overlapping_export"
                )
                candidate = native_candidates[result.intent_schedule.schedule_id]
                price = candidate.average_charge_window_price_eur_per_kwh
                if price is None:
                    continue
                # Keep both timing boundaries at the best price. Overlaying a
                # market window may consume one boundary while the other still
                # proves recovery. This is a semantic frontier, not a top-N
                # truncation, and remains bounded to two paths per timing role.
                for boundary, timing in (
                    ("earliest", grid_start.timestamp()),
                    ("latest", -grid_start.timestamp()),
                ):
                    key = f"{role}:{boundary}"
                    score = (price, timing)
                    retained = representatives.get(key)
                    if retained is None or score < retained[0]:
                        representatives[key] = (score, result)
            return tuple(
                dict.fromkeys(item[1] for item in representatives.values())
            )

        assessments: list[MarketRouteAssessment] = []
        for route in routes:
            # Stored-inventory export and negative-capacity routes already
            # describe a complete acquisition-independent path. Combining
            # every such route with every hybrid recovery parent creates a
            # Cartesian product of paths that represent a different route
            # family and made rolling-horizon planning grow explosively.
            # Acquisition-linked trade routes retain the hybrid parents added
            # by DEV.215 so PV + residual grid + evening trade remains a
            # first-class complete Energy Path.
            applicable_parents = (
                (baseline_result,)
                if route.route_kind in {"stored_energy_export", "negative_capacity"}
                else (baseline_result, *representative_hybrid_parents(route))
            )
            simulated_by_effective_path: dict[
                tuple[tuple[datetime, datetime, str, float], ...],
                DailyReferenceStrategyResult,
            ] = {}
            assessment_by_effective_path: dict[
                tuple[
                    tuple[tuple[datetime, datetime, str, float], ...],
                    str,
                ],
                MarketRouteAssessment,
            ] = {}
            for parent_result in applicable_parents:
                schedule = self._market_schedule(
                    parent_result.intent_schedule,
                    snapshot=snapshot,
                    route=route,
                    maximum_discharge_output_power_w=(inputs.maximum_discharge_output_power_w),
                )
                signature = tuple(
                    (
                        interval.starts_at,
                        interval.ends_at,
                        interval.intent.value,
                        interval.storage_export_target_wh,
                    )
                    for interval in schedule.intervals
                )
                market_result = simulated_by_effective_path.get(signature)
                if market_result is None:
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
                            maximum_discharge_output_power_w=(
                                inputs.maximum_discharge_output_power_w
                            ),
                        )
                        .strategy_results[0]
                    )
                    simulated_by_effective_path[signature] = market_result
                assessment = self._assessment(
                    route=route,
                    parent_result=parent_result,
                    market_result=market_result,
                    assessed_schedule=schedule,
                    wear_eur_per_export_kwh=trading_policy.wear_eur_per_export_kwh,
                    minimum_total_route_profit_eur=(
                        trading_policy.minimum_total_route_profit_eur
                    ),
                )
                parent_kind = (
                    "hybrid"
                    if parent_result.intent_schedule.schedule_id != baseline_schedule_id
                    else "baseline"
                )
                assessment_key = (signature, parent_kind)
                retained = assessment_by_effective_path.get(assessment_key)
                if retained is None or (
                    assessment.admitted,
                    assessment.worst_case_incremental_result_eur,
                    assessment.minimum_incremental_result_eur_per_exported_kwh,
                ) > (
                    retained.admitted,
                    retained.worst_case_incremental_result_eur,
                    retained.minimum_incremental_result_eur_per_exported_kwh,
                ):
                    assessment_by_effective_path[assessment_key] = assessment
            assessments.extend(assessment_by_effective_path.values())
        return tuple(assessments)

    @staticmethod
    def _market_schedule(
        baseline: DailyReferenceIntentSchedule,
        *,
        snapshot: PlanningInputSnapshot,
        route: MarketCapacityRoute,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceIntentSchedule:
        export_targets: dict[tuple[datetime, datetime], float] = {}
        remaining_output_wh = route.required_pre_window_discharge_output_wh
        candidate_intervals = (
            tuple(
                interval
                for interval in baseline.intervals
                if route.export_window_starts_at is not None
                and route.export_window_ends_at is not None
                and interval.starts_at < route.export_window_ends_at
                and interval.ends_at > route.export_window_starts_at
            )
            if route.route_kind
            in {
                "grid_trade",
                "pv_trade",
                "pv_trade_grid_recovery",
                "stored_energy_export",
            }
            else tuple(
                interval
                for interval in reversed(baseline.intervals)
                if interval.ends_at <= route.window_starts_at
            )
        )
        for interval in candidate_intervals:
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
        final_export_end = max(
            (ends_at for _starts_at, ends_at in export_targets),
            default=None,
        )
        for item in baseline.intervals:
            inside_explicit_charge = (
                route.route_kind in {"grid_trade", "negative_capacity", "pv_trade_grid_recovery"}
                and route.maximum_charge_input_wh > 0.0
                and item.starts_at < route.window_ends_at
                and item.ends_at > route.window_starts_at
            )
            inside_pv_preference_window = (
                route.route_kind
                in {
                    "grid_trade",
                    "pv_trade",
                    "pv_trade_grid_recovery",
                }
                and item.starts_at < route.opportunity_window_ends_at
                and item.ends_at > route.opportunity_window_starts_at
            )
            intent = (
                DailyStorageIntent.GRID_REQUIREMENT
                if inside_explicit_charge
                else DailyStorageIntent.STORAGE_EXPORT
                if (item.starts_at, item.ends_at) in export_targets
                else DailyStorageIntent.NOM
                if inside_pv_preference_window
                else item.intent
            )
            if (
                intent is DailyStorageIntent.NOM
                and final_export_end is not None
                and item.starts_at >= final_export_end
                and not MarketDailyPlanner._has_possible_pv(
                    snapshot,
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                )
            ):
                intent = DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
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
                route.route_kind == "stored_energy_export"
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
                    "physical_baseline_or_reserve_not_restored"
                    if not physically_admissible
                    else "minimum_total_route_profit_not_met"
                )
            ),
            scenario_evidence=tuple(scenario_evidence),
            method_version=METHOD_VERSION,
            minimum_total_route_profit_eur=minimum_total_route_profit_eur,
        )
