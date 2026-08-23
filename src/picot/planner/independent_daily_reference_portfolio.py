"""Produce comparable complete runs for independent daily intent schedules."""

from __future__ import annotations

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_intent import DailyReferenceIntentSchedule
from picot.domain.daily_reference_portfolio import (
    DailyReferencePortfolio,
    DailyReferenceStrategyResult,
)
from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_intent_simulator import (
    IndependentDailyIntentSimulator,
)
from picot.planner.independent_daily_reference_run import (
    IndependentDailyReferenceRunProducer,
)
from picot.planner.independent_daily_simulator import ScenarioTimeline

METHOD_VERSION = "independent-daily-reference-portfolio:v1"


class IndependentDailyReferencePortfolioProducer:
    """Simulate every supplied strategy from one identical immutable input set."""

    def produce(
        self,
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        tariffs: DailyReferenceTariffSchedule,
        intent_schedules: tuple[DailyReferenceIntentSchedule, ...],
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferencePortfolio:
        if not intent_schedules:
            raise ValueError("Daily strategy portfolio requires intent schedules.")
        if tariffs.snapshot_id != snapshot_id:
            raise ValueError("Daily portfolio tariff and input snapshots must match.")
        results = tuple(
            self._produce_strategy(
                snapshot_id=snapshot_id,
                household=household,
                pv_scenarios=pv_scenarios,
                storage_state=storage_state,
                conversion_model=conversion_model,
                tariffs=tariffs,
                intent_schedule=intent_schedule,
                minimum_storage_energy_wh=minimum_storage_energy_wh,
                target_storage_energy_wh=target_storage_energy_wh,
                maximum_charge_input_power_w=maximum_charge_input_power_w,
                maximum_discharge_output_power_w=maximum_discharge_output_power_w,
            )
            for intent_schedule in intent_schedules
        )
        return DailyReferencePortfolio(
            portfolio_id=f"daily-portfolio:{snapshot_id}",
            snapshot_id=snapshot_id,
            tariff_schedule_id=tariffs.schedule_id,
            strategy_results=results,
            observer_only=True,
            ranking_permitted=False,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _produce_strategy(
        *,
        snapshot_id: str,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        tariffs: DailyReferenceTariffSchedule,
        intent_schedule: DailyReferenceIntentSchedule,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceStrategyResult:
        simulation = IndependentDailyIntentSimulator().simulate(
            snapshot_id=snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            conversion_model=conversion_model,
            intent_schedule=intent_schedule,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
        )
        run = IndependentDailyReferenceRunProducer().produce(
            simulation=simulation,
            tariffs=tariffs,
        )
        return DailyReferenceStrategyResult(
            strategy_result_id=f"daily-strategy:{run.run_id}",
            intent_schedule=intent_schedule,
            run=run,
        )
