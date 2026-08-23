"""Run an entire generated daily strategy space through the observer chain."""

from __future__ import annotations

from picot.domain.current_storage_state import CurrentStorageState
from picot.domain.daily_reference_strategy_observation import (
    DailyReferenceStrategyObservation,
)
from picot.domain.daily_reference_strategy_space import DailyReferenceStrategySpace
from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.domain.household_load_forecast import HouseholdLoadForecast
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_observer import IndependentDailyObserver
from picot.planner.independent_daily_reference_portfolio import (
    IndependentDailyReferencePortfolioProducer,
)
from picot.planner.independent_daily_simulator import ScenarioTimeline

METHOD_VERSION = "independent-daily-strategy-observer:v1"


class IndependentDailyStrategyObserver:
    """Simulate, settle, form and evaluate every generated strategy exactly once."""

    def observe(
        self,
        *,
        strategy_space: DailyReferenceStrategySpace,
        household: HouseholdLoadForecast,
        pv_scenarios: tuple[ScenarioTimeline, ...],
        storage_state: CurrentStorageState,
        conversion_model: StorageConversionModel,
        tariffs: DailyReferenceTariffSchedule,
        minimum_storage_energy_wh: float,
        target_storage_energy_wh: float,
        maximum_charge_input_power_w: float,
        maximum_discharge_output_power_w: float,
    ) -> DailyReferenceStrategyObservation:
        portfolio = IndependentDailyReferencePortfolioProducer().produce(
            snapshot_id=strategy_space.snapshot_id,
            household=household,
            pv_scenarios=pv_scenarios,
            storage_state=storage_state,
            conversion_model=conversion_model,
            tariffs=tariffs,
            intent_schedules=strategy_space.schedules,
            minimum_storage_energy_wh=minimum_storage_energy_wh,
            target_storage_energy_wh=target_storage_energy_wh,
            maximum_charge_input_power_w=maximum_charge_input_power_w,
            maximum_discharge_output_power_w=maximum_discharge_output_power_w,
        )
        observer_result = IndependentDailyObserver().observe(portfolio)
        return DailyReferenceStrategyObservation(
            observation_id=f"daily-strategy-observation:{strategy_space.snapshot_id}",
            snapshot_id=strategy_space.snapshot_id,
            strategy_space=strategy_space,
            observer_result=observer_result,
            observer_only=True,
            selection_permitted=False,
            commitment_permitted=False,
            method_version=METHOD_VERSION,
        )
