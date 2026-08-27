"""Independent Market Daily Planner built directly from Planning Input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

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
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    IndependentDailyReferenceAdapter,
)
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

METHOD_VERSION = "market-daily-planner:v1"
MARKET_DAILY_MAXIMUM_DURATION = timedelta(hours=36)


@dataclass(frozen=True, slots=True)
class MarketTradingPolicy:
    margin_fraction: float = 0.10
    wear_eur_per_export_kwh: float = 0.05
    market_routes_enabled: bool = True
    minimum_total_route_profit_eur: float = 0.05

    def __post_init__(self) -> None:
        if not 0.0 <= self.margin_fraction <= 1.0:
            raise ValueError("MEP trading margin must be between 0 and 1")
        if not 0.0 <= self.wear_eur_per_export_kwh <= 1.0:
            raise ValueError("MEP wear cost must be between 0 and 1 EUR/kWh")
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
    window_starts_at: datetime
    window_ends_at: datetime
    maximum_charge_input_wh: float
    reserved_storage_room_wh: float
    storage_energy_ceiling_before_window_wh: float
    required_pre_window_discharge_output_wh: float
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
        if self.window_ends_at <= self.window_starts_at:
            raise ValueError("MEP market window must have positive duration.")
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
    household_demand_wh: float
    incremental_financial_result_eur: float
    exported_energy_kwh: float


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
            and self.worst_case_incremental_result_eur
            >= self.minimum_total_route_profit_eur
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
    """Plan MEP end-to-end without consuming CP or EP output."""

    def plan(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy | None = None,
        dispatch_authority: bool = False,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory: StorageEnergyInventory | None = None,
    ) -> MarketDailyPlan:
        plan, _ = self.plan_with_diagnostics(
            snapshot=snapshot,
            conversion_model=conversion_model,
            trading_policy=trading_policy,
            dispatch_authority=dispatch_authority,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
            storage_inventory=storage_inventory,
        )
        return plan

    def plan_with_diagnostics(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy | None = None,
        dispatch_authority: bool = False,
        micro_charge_suppression_fraction: float = 0.01,
        storage_inventory: StorageEnergyInventory | None = None,
    ) -> tuple[MarketDailyPlan, MarketDailyPlannerDiagnostics]:
        planner_started = perf_counter()
        trading_policy = trading_policy or MarketTradingPolicy()
        # This is a private MEP planning run from the shared immutable input.
        # No CP/EP runtime, persisted observation or winner is consulted.
        phase_started = perf_counter()
        native_observation = IndependentDailyReferenceAdapter().observe(
            snapshot=snapshot,
            conversion_model=conversion_model,
            maximum_duration=MARKET_DAILY_MAXIMUM_DURATION,
            micro_charge_suppression_fraction=micro_charge_suppression_fraction,
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
        )
        market_route_assessment_ms = (perf_counter() - phase_started) * 1000.0
        phase_started = perf_counter()
        market_wins = any(item.admitted for item in assessments)
        current_intent, current_interval_ends_at = self._current_decision(
            snapshot=snapshot,
            native_observation=native_observation,
            assessments=assessments,
        )
        plan = MarketDailyPlan(
            planner_id="mep",
            planner_name="Markt Etmaal Planner",
            snapshot_id=snapshot.snapshot_id,
            native_observation=native_observation,
            market_routes=routes,
            route_assessments=assessments,
            winning_source=("market_route" if market_wins else "mep_native_plan"),
            reason=(
                "profitable_complete_market_route"
                if market_wins
                else (
                    "market_recovery_outside_available_horizon"
                    if not routes and recovery_outside_horizon
                    else "no_admitted_market_route"
                )
            ),
            dispatch_authority=dispatch_authority,
            current_intent=current_intent,
            current_interval_ends_at=current_interval_ends_at,
            method_version=METHOD_VERSION,
            round_trip_efficiency=(
                conversion_model.charge_efficiency * conversion_model.discharge_efficiency
            ),
            trading_margin_fraction=trading_policy.margin_fraction,
            wear_eur_per_export_kwh=trading_policy.wear_eur_per_export_kwh,
            minimum_total_route_profit_eur=(
                trading_policy.minimum_total_route_profit_eur
            ),
        )
        winner_selection_ms = (perf_counter() - phase_started) * 1000.0
        candidates = native_observation.observer_result.candidate_set.candidates
        diagnostics = MarketDailyPlannerDiagnostics(
            native_plan_ms=round(native_plan_ms, 3),
            tariff_build_ms=round(tariff_build_ms, 3),
            market_route_build_ms=round(market_route_build_ms, 3),
            market_route_assessment_ms=round(market_route_assessment_ms, 3),
            winner_selection_ms=round(winner_selection_ms, 3),
            planner_total_ms=round((perf_counter() - planner_started) * 1000.0, 3),
            native_candidate_count=len(candidates),
            market_route_count=len(routes),
            route_assessment_count=len(assessments),
        )
        return plan, diagnostics

    @staticmethod
    def _market_routes(
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
        trading_policy: MarketTradingPolicy,
        storage_inventory: StorageEnergyInventory | None,
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
        negative_groups: list[list[DailyReferenceTariffInterval]] = []
        for interval in tariffs.intervals:
            if interval.import_eur_per_kwh >= 0.0:
                continue
            if negative_groups and negative_groups[-1][-1].ends_at == interval.starts_at:
                negative_groups[-1].append(interval)
            else:
                negative_groups.append([interval])

        maximum_energy_wh = limits.maximum_soc * storage.usable_capacity_wh
        minimum_energy_wh = limits.minimum_soc * storage.usable_capacity_wh
        current_energy_wh = storage.current_soc * storage.usable_capacity_wh
        usable_storage_range_wh = maximum_energy_wh - minimum_energy_wh
        result: list[MarketCapacityRoute] = []
        for group in negative_groups:
            starts_at = group[0].starts_at
            ends_at = group[-1].ends_at
            duration_hours = (ends_at - starts_at).total_seconds() / 3600.0
            maximum_charge_input_wh = limits.maximum_charge_input_power_w * duration_hours
            reserved_storage_room_wh = min(
                usable_storage_range_wh,
                maximum_charge_input_wh * conversion_model.charge_efficiency,
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
                    window_starts_at=starts_at,
                    window_ends_at=ends_at,
                    maximum_charge_input_wh=maximum_charge_input_wh,
                    reserved_storage_room_wh=reserved_storage_room_wh,
                    storage_energy_ceiling_before_window_wh=ceiling_wh,
                    required_pre_window_discharge_output_wh=(
                        required_stored_discharge_wh * conversion_model.discharge_efficiency
                    ),
                    reason="negative_all_in_import_window",
                    method_version=METHOD_VERSION,
                )
            )
        # Ordinary grid trading is a complete charge-then-export route.  It is
        # deliberately generated from MEP's own tariffs, never from an EP
        # candidate or winner.  Full physical simulation and incremental
        # settlement below remain the admission authority.
        future = tuple(item for item in tariffs.intervals if item.ends_at > snapshot.captured_at)
        interval_windows = tuple(
            tuple(future[index : index + width])
            for width in range(1, min(8, len(future)) + 1)
            for index in range(0, len(future) - width + 1)
            if all(
                left.ends_at == right.starts_at
                for left, right in zip(
                    future[index : index + width],
                    future[index + 1 : index + width],
                    strict=False,
                )
            )
        )
        trade_candidates: list[
            tuple[
                float,
                tuple[DailyReferenceTariffInterval, ...],
                tuple[DailyReferenceTariffInterval, ...],
                float,
                float,
            ]
        ] = []
        for charge_window in interval_windows:
            charge_start = charge_window[0].starts_at
            charge_end = charge_window[-1].ends_at
            charge_hours = (charge_end - charge_start).total_seconds() / 3600
            charge_rate = sum(
                item.import_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                for item in charge_window
            ) / ((charge_end - charge_start).total_seconds())
            for export_window in interval_windows:
                if export_window[0].starts_at < charge_end:
                    continue
                export_start = export_window[0].starts_at
                export_end = export_window[-1].ends_at
                export_hours = (export_end - export_start).total_seconds() / 3600
                export_rate = sum(
                    item.export_eur_per_kwh * (item.ends_at - item.starts_at).total_seconds()
                    for item in export_window
                ) / ((export_end - export_start).total_seconds())
                charge_input_wh = min(
                    usable_storage_range_wh / conversion_model.charge_efficiency,
                    limits.maximum_charge_input_power_w * charge_hours,
                    limits.maximum_discharge_output_power_w
                    * export_hours
                    / (conversion_model.charge_efficiency * conversion_model.discharge_efficiency),
                )
                export_output_wh = (
                    charge_input_wh
                    * conversion_model.charge_efficiency
                    * conversion_model.discharge_efficiency
                )
                indicated_result = (
                    export_output_wh / 1000 * export_rate
                    - charge_input_wh / 1000 * charge_rate
                    - export_output_wh / 1000 * trading_policy.wear_eur_per_export_kwh
                )
                if export_output_wh > 0:
                    trade_candidates.append(
                        (
                            indicated_result,
                            charge_window,
                            export_window,
                            charge_input_wh,
                            export_output_wh,
                        )
                    )
        for (
            _indicated_result,
            charge_window,
            export_window,
            charge_input_wh,
            export_output_wh,
        ) in sorted(
            trade_candidates,
            key=lambda item: item[0],
            reverse=True,
        )[:6]:
            charge_start = charge_window[0].starts_at
            charge_end = charge_window[-1].ends_at
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
            charge_rate = sum(
                item.import_eur_per_kwh
                * (item.ends_at - item.starts_at).total_seconds()
                for item in charge_window
            ) / ((charge_end - charge_start).total_seconds())
            export_rate = sum(
                item.export_eur_per_kwh
                * (item.ends_at - item.starts_at).total_seconds()
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
                        f"{charge_start.isoformat()}:"
                        f"{export_start.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    window_starts_at=charge_start,
                    window_ends_at=charge_end,
                    maximum_charge_input_wh=charge_input_wh,
                    reserved_storage_room_wh=(charge_input_wh * conversion_model.charge_efficiency),
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
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
        # PV trade candidates do not invent an acquisition price.  They retain
        # MEP's own PV/NOM schedule and only test whether demonstrably surplus
        # stored energy can be exported in a high-value interval while the
        # target and reserve remain protected in every PV scenario.
        pv_trade_candidates: list[
            tuple[
                float,
                tuple[DailyReferenceTariffInterval, ...],
                tuple[DailyReferenceTariffInterval, ...],
                float,
                float,
                StorageEnergyCostAllocation | None,
            ]
        ] = []
        rte = conversion_model.charge_efficiency * conversion_model.discharge_efficiency
        recovery_outside_horizon = False
        cheapest_known_recharge_rate = min(
            (item.import_eur_per_kwh for item in future),
            default=0.0,
        )
        for export_window in interval_windows:
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
            export_hours = (export_end - export_start).total_seconds() / 3600
            export_output_wh = min(
                usable_storage_range_wh,
                limits.maximum_discharge_output_power_w * export_hours,
            )
            inventory_allocation = None
            if storage_inventory is not None:
                if (
                    storage_inventory.execution_scope_id
                    != storage.execution_scope_id
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
            recovery_windows: list[tuple[DailyReferenceTariffInterval, ...]] = []
            for start_index, first in enumerate(future):
                if first.starts_at < export_end:
                    continue
                recovery_intervals: list[DailyReferenceTariffInterval] = []
                available_input_wh = 0.0
                for interval in future[start_index:]:
                    if recovery_intervals and recovery_intervals[-1].ends_at != interval.starts_at:
                        break
                    recovery_intervals.append(interval)
                    duration_hours = (
                        interval.ends_at - interval.starts_at
                    ).total_seconds() / 3600.0
                    available_input_wh += limits.maximum_charge_input_power_w * duration_hours
                    if available_input_wh >= required_recharge_input_wh:
                        recovery_windows.append(tuple(recovery_intervals))
                        break
            recovery_candidates = []
            for recovery_window in recovery_windows:
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
                recovery_candidates.append((recharge_rate, recovery_window))
            if not recovery_candidates:
                if export_rate >= trading_policy.minimum_export_rate(
                    cheapest_known_recharge_rate,
                    rte,
                ):
                    recovery_outside_horizon = True
                continue
            lowest_recharge_rate = min(item[0] for item in recovery_candidates)
            recharge_rate, recovery_window = max(
                (item for item in recovery_candidates if item[0] == lowest_recharge_rate),
                key=lambda item: item[1][0].starts_at,
            )
            minimum_export_rate = trading_policy.minimum_export_rate(recharge_rate, rte)
            if inventory_allocation is not None:
                inventory_rate = (
                    inventory_allocation.acquisition_cost_eur
                    / (inventory_allocation.deliverable_energy_wh / 1000.0)
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
                    export_window,
                    recovery_window,
                    export_output_wh,
                    minimum_export_rate,
                    inventory_allocation,
                )
            )
        for (
            _,
            export_window,
            recovery_window,
            export_output_wh,
            minimum_export_rate,
            inventory_allocation,
        ) in sorted(
            pv_trade_candidates,
            key=lambda item: (item[0], item[3]),
            reverse=True,
        )[:8]:
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
                inventory_allocation.sources
                if inventory_allocation is not None
                else ()
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
                    window_starts_at=recovery_start,
                    window_ends_at=recovery_end,
                    maximum_charge_input_wh=0.0,
                    reserved_storage_room_wh=0.0,
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
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
            # consumption, assess the same export with the cheapest feasible
            # later grid-recovery window inside the available horizon.
            result.append(
                MarketCapacityRoute(
                    route_id=(
                        f"mep-pv-trade-grid-recovery:{snapshot.snapshot_id}:"
                        f"{export_start.isoformat()}:{export_end.isoformat()}:"
                        f"{recovery_start.isoformat()}:{recovery_end.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    window_starts_at=recovery_start,
                    window_ends_at=recovery_end,
                    maximum_charge_input_wh=recharge_input_wh,
                    reserved_storage_room_wh=(
                        recharge_input_wh * conversion_model.charge_efficiency
                    ),
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
                    export_window_starts_at=export_start,
                    export_window_ends_at=export_end,
                    route_kind="pv_trade_grid_recovery",
                    reason="export_then_restore_from_cheapest_next_day_grid_window",
                    average_export_eur_per_kwh=export_rate,
                    average_recharge_eur_per_kwh=recharge_rate,
                    minimum_export_eur_per_kwh=minimum_export_rate,
                    inventory_deliverable_energy_wh=inventory_deliverable_energy_wh,
                    inventory_acquisition_cost_eur=inventory_acquisition_cost_eur,
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
    ) -> tuple[MarketRouteAssessment, ...]:
        if not routes:
            return ()
        candidates = {
            item.candidate_id: item
            for item in native_observation.observer_result.candidate_set.candidates
        }
        results = {
            item.intent_schedule.schedule_id: item
            for item in native_observation.observer_result.portfolio.strategy_results
        }
        native_winner_id = sorted(native_observation.observer_result.best_observation_ids)[0]
        baseline_results = (results[candidates[native_winner_id].intent_schedule_id],)
        adapter = IndependentDailyReferenceAdapter()
        inputs = adapter.build_inputs(
            snapshot,
            horizon_end=tariffs.horizon_end,
            maximum_duration=MARKET_DAILY_MAXIMUM_DURATION,
        )
        assessments: list[MarketRouteAssessment] = []
        for route in routes:
            for baseline_result in baseline_results:
                schedule = self._market_schedule(
                    baseline_result.intent_schedule,
                    route=route,
                    maximum_discharge_output_power_w=(inputs.maximum_discharge_output_power_w),
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
                        baseline_result=baseline_result,
                        market_result=market_result,
                        wear_eur_per_export_kwh=trading_policy.wear_eur_per_export_kwh,
                        minimum_total_route_profit_eur=(
                            trading_policy.minimum_total_route_profit_eur
                        ),
                    )
                )
        return tuple(assessments)

    @staticmethod
    def _current_decision(
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        assessments: tuple[MarketRouteAssessment, ...],
    ) -> tuple[DailyStorageIntent | None, datetime | None]:
        admitted = tuple(item for item in assessments if item.admitted)
        schedules: tuple[DailyReferenceIntentSchedule, ...]
        if admitted:
            winner = max(
                admitted,
                key=lambda item: (
                    item.worst_case_incremental_result_eur,
                    item.minimum_incremental_result_eur_per_exported_kwh,
                    item.market_schedule_id,
                ),
            )
            schedules = (winner.intent_schedule,)
        else:
            candidates = {
                item.candidate_id: item
                for item in native_observation.observer_result.candidate_set.candidates
            }
            results = {
                item.intent_schedule.schedule_id: item.intent_schedule
                for item in native_observation.observer_result.portfolio.strategy_results
            }
            native_winner_ids = sorted(
                native_observation.observer_result.best_observation_ids
            )
            if native_winner_ids:
                schedules = (
                    results[candidates[native_winner_ids[0]].intent_schedule_id],
                )
            else:
                schedules = (native_observation.strategy_space.schedules[0],)
        due = tuple(
            next(
                (
                    interval
                    for interval in schedule.intervals
                    if interval.starts_at <= snapshot.captured_at < interval.ends_at
                ),
                None,
            )
            for schedule in schedules
        )
        if not due or any(item is None for item in due):
            return None, None
        decisions = {(item.intent, item.ends_at) for item in due if item is not None}
        if len(decisions) != 1:
            return None, None
        return next(iter(decisions))

    @staticmethod
    def _market_schedule(
        baseline: DailyReferenceIntentSchedule,
        *,
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
            if route.route_kind in {"grid_trade", "pv_trade", "pv_trade_grid_recovery"}
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
        intervals = tuple(
            DailyReferenceIntentInterval(
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                intent=(
                    DailyStorageIntent.GRID_REQUIREMENT
                    if route.route_kind
                    in {"grid_trade", "negative_capacity", "pv_trade_grid_recovery"}
                    and route.maximum_charge_input_wh > 0.0
                    and item.starts_at < route.window_ends_at
                    and item.ends_at > route.window_starts_at
                    else (
                        DailyStorageIntent.STORAGE_EXPORT
                        if (item.starts_at, item.ends_at) in export_targets
                        else item.intent
                    )
                ),
                storage_export_target_wh=export_targets.get(
                    (item.starts_at, item.ends_at),
                    0.0,
                ),
            )
            for item in baseline.intervals
        )
        return DailyReferenceIntentSchedule(
            schedule_id=schedule_id,
            snapshot_id=baseline.snapshot_id,
            horizon_start=baseline.horizon_start,
            horizon_end=baseline.horizon_end,
            intervals=intervals,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _assessment(
        *,
        route: MarketCapacityRoute,
        baseline_result: DailyReferenceStrategyResult,
        market_result: DailyReferenceStrategyResult,
        wear_eur_per_export_kwh: float,
        minimum_total_route_profit_eur: float,
    ) -> MarketRouteAssessment:
        baseline_run = baseline_result.run
        market_run = market_result.run
        baseline_assessment = {item.scenario: item for item in baseline_run.assessment.assessments}
        market_assessment = {item.scenario: item for item in market_run.assessment.assessments}
        baseline_financial = {item.scenario: item for item in baseline_run.financial.paths}
        market_financial = {item.scenario: item for item in market_run.financial.paths}
        incremental_results: list[float] = []
        result_per_export_kwh: list[float] = []
        wear_values: list[float] = []
        scenario_evidence: list[MarketRouteScenarioEvidence] = []
        market_trajectories = {
            item.scenario: item for item in market_run.simulation.trajectories
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
                    target_reached_during_horizon=(
                        market_flow.target_reached_during_horizon
                    ),
                    target_held_at_horizon_end=(
                        market_flow.target_held_at_horizon_end
                    ),
                    target_storage_energy_wh=trajectory.target_storage_energy_wh,
                    minimum_storage_energy_wh=trajectory.minimum_storage_energy_wh,
                    minimum_storage_energy_observed_wh=(
                        market_flow.minimum_storage_energy_observed_wh
                    ),
                    storage_energy_at_horizon_end_wh=(
                        market_flow.storage_energy_at_horizon_end_wh
                    ),
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
                        interval.grid_to_storage_input_wh
                        for interval in trajectory.intervals
                    ),
                    household_demand_wh=market_flow.household_demand_wh,
                    incremental_financial_result_eur=incremental_eur,
                    exported_energy_kwh=extra_export_kwh,
                )
            )
        physically_admissible = all(
            item.physically_complete
            and item.reserve_respected
            and item.storage_energy_at_horizon_end_wh + 1e-6
            >= baseline_assessment[scenario].storage_energy_at_horizon_end_wh
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
            source_native_schedule_id=baseline_result.intent_schedule.schedule_id,
            market_schedule_id=market_result.intent_schedule.schedule_id,
            intent_schedule=market_result.intent_schedule,
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
