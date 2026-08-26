"""Independent Market Daily Planner built directly from Planning Input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
from picot.planner.independent_daily_reference_portfolio import (
    IndependentDailyReferencePortfolioProducer,
)
from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.independent_daily_reference_adapter import (
    IndependentDailyReferenceAdapter,
)
from picot.v2.independent_daily_tariff_adapter import (
    EXPORT_TAX_TRANSITION,
    IndependentDailyTariffAdapter,
)

METHOD_VERSION = "market-daily-planner:v1"
INCREMENTAL_WEAR_EUR_PER_OUTPUT_KWH = 0.04917
MINIMUM_TRADING_RESULT_EUR = 0.25
MINIMUM_TRADING_RESULT_EUR_PER_EXPORT_KWH = 0.05


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
        if self.route_kind not in {"negative_capacity", "grid_trade", "pv_trade"}:
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
    method_version: str

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
            and self.worst_case_incremental_result_eur >= MINIMUM_TRADING_RESULT_EUR
            and self.minimum_incremental_result_eur_per_exported_kwh
            >= MINIMUM_TRADING_RESULT_EUR_PER_EXPORT_KWH
        )
        if self.admitted != expected_admission:
            raise ValueError("MEP route admission must reconcile.")


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

    def __post_init__(self) -> None:
        if self.planner_id != "mep" or self.planner_name != "Markt Etmaal Planner":
            raise ValueError("MEP identity must remain explicit.")
        if self.native_observation.snapshot_id != self.snapshot_id:
            raise ValueError("MEP native plan must share its Planning Input snapshot.")
        if not self.method_version.strip():
            raise ValueError("MEP method version must be explicit.")
        admitted = any(item.admitted for item in self.route_assessments)
        expected_source = "market_route" if admitted else "mep_native_plan"
        if self.winning_source != expected_source:
            raise ValueError("MEP winner source must reconcile with route admission.")
        if (self.current_intent is None) != (self.current_interval_ends_at is None):
            raise ValueError("MEP current intent and interval end must be paired.")


class MarketDailyPlanner:
    """Plan MEP end-to-end without consuming CP or EP output."""

    def plan(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        conversion_model: StorageConversionModel,
        dispatch_authority: bool = False,
    ) -> MarketDailyPlan:
        # This is a private MEP planning run from the shared immutable input.
        # No CP/EP runtime, persisted observation or winner is consulted.
        native_observation = IndependentDailyReferenceAdapter().observe(
            snapshot=snapshot,
            conversion_model=conversion_model,
        )
        horizon_end = native_observation.strategy_space.schedules[0].horizon_end
        tariffs = IndependentDailyTariffAdapter().build(
            snapshot,
            horizon_end=horizon_end,
        )
        routes = self._market_routes(
            snapshot=snapshot,
            tariffs=tariffs,
            conversion_model=conversion_model,
        )
        assessments = self._assess_routes(
            snapshot=snapshot,
            native_observation=native_observation,
            tariffs=tariffs,
            conversion_model=conversion_model,
            routes=routes,
        )
        market_wins = any(item.admitted for item in assessments)
        current_intent, current_interval_ends_at = self._current_decision(
            captured_at=snapshot.captured_at,
            native_observation=native_observation,
            assessments=assessments,
        )
        return MarketDailyPlan(
            planner_id="mep",
            planner_name="Markt Etmaal Planner",
            snapshot_id=snapshot.snapshot_id,
            native_observation=native_observation,
            market_routes=routes,
            route_assessments=assessments,
            winning_source=("market_route" if market_wins else "mep_native_plan"),
            reason=(
                "profitable_complete_market_route" if market_wins else "no_admitted_market_route"
            ),
            dispatch_authority=dispatch_authority,
            current_intent=current_intent,
            current_interval_ends_at=current_interval_ends_at,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _market_routes(
        *,
        snapshot: PlanningInputSnapshot,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
    ) -> tuple[MarketCapacityRoute, ...]:
        if len(snapshot.current_storage_states) != 1:
            return ()
        storage = snapshot.current_storage_states[0]
        matching_limits = tuple(
            item
            for item in snapshot.storage_physical_limits
            if item.capability_id == storage.capability_id
            and item.execution_scope_id == storage.execution_scope_id
        )
        if len(matching_limits) != 1:
            return ()
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
                    - export_output_wh / 1000 * INCREMENTAL_WEAR_EUR_PER_OUTPUT_KWH
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
            indicated_result,
            charge_window,
            export_window,
            charge_input_wh,
            export_output_wh,
        ) in sorted(
            trade_candidates,
            key=lambda item: item[0],
            reverse=True,
        )[:6]:
            # Through 2026 a grid-imported kWh only receives saldering value
            # when origin and remaining entitlement are proven. Planning Input
            # has no such evidence contract yet, so ordinary grid arbitrage
            # fails closed. Negative-price capacity routes remain separately
            # settled as complete linked routes.
            if charge_window[0].starts_at < EXPORT_TAX_TRANSITION:
                continue
            if indicated_result < MINIMUM_TRADING_RESULT_EUR or (
                indicated_result / (export_output_wh / 1000)
                < MINIMUM_TRADING_RESULT_EUR_PER_EXPORT_KWH
            ):
                continue
            charge_start = charge_window[0].starts_at
            charge_end = charge_window[-1].ends_at
            export_start = export_window[0].starts_at
            export_end = export_window[-1].ends_at
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
                    method_version=METHOD_VERSION,
                )
            )
        # PV trade candidates do not invent an acquisition price.  They retain
        # MEP's own PV/NOM schedule and only test whether demonstrably surplus
        # stored energy can be exported in a high-value interval while the
        # target and reserve remain protected in every PV scenario.
        for export in sorted(
            future,
            key=lambda item: item.export_eur_per_kwh,
            reverse=True,
        )[:8]:
            earlier_export_values = tuple(
                item.export_eur_per_kwh for item in future if item.ends_at <= export.starts_at
            )
            if not earlier_export_values:
                continue
            indicated_margin = (
                export.export_eur_per_kwh
                - min(earlier_export_values)
                - INCREMENTAL_WEAR_EUR_PER_OUTPUT_KWH
            )
            if indicated_margin < MINIMUM_TRADING_RESULT_EUR_PER_EXPORT_KWH:
                continue
            export_hours = (export.ends_at - export.starts_at).total_seconds() / 3600
            export_output_wh = min(
                usable_storage_range_wh,
                limits.maximum_discharge_output_power_w * export_hours,
            )
            if export_output_wh <= 0.0:
                continue
            result.append(
                MarketCapacityRoute(
                    route_id=(
                        f"mep-pv-trade:{snapshot.snapshot_id}:{export.starts_at.isoformat()}"
                    ),
                    snapshot_id=snapshot.snapshot_id,
                    window_starts_at=export.starts_at,
                    window_ends_at=export.ends_at,
                    maximum_charge_input_wh=0.0,
                    reserved_storage_room_wh=0.0,
                    storage_energy_ceiling_before_window_wh=maximum_energy_wh,
                    required_pre_window_discharge_output_wh=export_output_wh,
                    export_window_starts_at=export.starts_at,
                    export_window_ends_at=export.ends_at,
                    route_kind="pv_trade",
                    reason="shift_proven_pv_surplus_to_export_window",
                    method_version=METHOD_VERSION,
                )
            )
        # Stable de-duplication: the same cheapest/highest pair can be reached
        # through overlapping rankings, but it must be simulated only once.
        return tuple({item.route_id: item for item in result}.values())

    def _assess_routes(
        self,
        *,
        snapshot: PlanningInputSnapshot,
        native_observation: DailyReferenceStrategyObservation,
        tariffs: DailyReferenceTariffSchedule,
        conversion_model: StorageConversionModel,
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
        inputs = adapter.build_inputs(snapshot, horizon_end=tariffs.horizon_end)
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
                    )
                )
        return tuple(assessments)

    @staticmethod
    def _current_decision(
        *,
        captured_at: datetime,
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
            native_winner_id = sorted(native_observation.observer_result.best_observation_ids)[0]
            schedules = (results[candidates[native_winner_id].intent_schedule_id],)
        due = tuple(
            next(
                (
                    interval
                    for interval in schedule.intervals
                    if interval.starts_at <= captured_at < interval.ends_at
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
            if route.route_kind in {"grid_trade", "pv_trade"}
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
                    if route.route_kind in {"grid_trade", "negative_capacity"}
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
        for scenario in PVScenario:
            baseline_flow = baseline_assessment[scenario]
            market_flow = market_assessment[scenario]
            baseline_output_wh = (
                baseline_flow.storage_to_household_output_wh
                + baseline_flow.storage_to_grid_output_wh
            )
            market_output_wh = (
                market_flow.storage_to_household_output_wh + market_flow.storage_to_grid_output_wh
            )
            extra_output_kwh = max(0.0, market_output_wh - baseline_output_wh) / 1000.0
            wear_eur = extra_output_kwh * INCREMENTAL_WEAR_EUR_PER_OUTPUT_KWH
            incremental_eur = (
                market_financial[scenario].net_financial_result_eur
                - baseline_financial[scenario].net_financial_result_eur
                - wear_eur
            )
            extra_export_kwh = (
                max(
                    0.0,
                    market_flow.storage_to_grid_output_wh - baseline_flow.storage_to_grid_output_wh,
                )
                / 1000.0
            )
            incremental_results.append(incremental_eur)
            wear_values.append(wear_eur)
            result_per_export_kwh.append(
                incremental_eur / extra_export_kwh if extra_export_kwh > 0.0 else float("-inf")
            )
        physically_admissible = all(
            item.physically_complete
            and item.reserve_respected
            and (
                item.target_held_at_horizon_end
                if route.route_kind == "pv_trade"
                else item.storage_energy_at_horizon_end_wh
                >= baseline_assessment[scenario].storage_energy_at_horizon_end_wh
            )
            for scenario, item in market_assessment.items()
        )
        worst_result = min(incremental_results)
        minimum_per_export = min(result_per_export_kwh)
        admitted = (
            physically_admissible
            and worst_result >= MINIMUM_TRADING_RESULT_EUR
            and minimum_per_export >= MINIMUM_TRADING_RESULT_EUR_PER_EXPORT_KWH
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
            method_version=METHOD_VERSION,
        )
