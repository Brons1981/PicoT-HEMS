from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_simulation import PVScenario
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_strategy_generator import (
    IndependentDailyStrategyGenerator,
)
from picot.planner.independent_daily_strategy_observer import (
    IndependentDailyStrategyObserver,
)
from test_independent_daily_reference_portfolio import (
    _tariffs_for_schedule_snapshot,
)
from test_independent_daily_simulator import (
    _household,
    _storage,
    _timeline,
)


def _observe():
    household = _household()
    strategy_space = IndependentDailyStrategyGenerator().generate(
        snapshot_id="snapshot-intent",
        household=household,
        window_lengths_intervals=(1,),
    )
    return IndependentDailyStrategyObserver().observe(
        strategy_space=strategy_space,
        household=household,
        pv_scenarios=tuple(_timeline(scenario) for scenario in PVScenario),
        storage_state=_storage(0.5),
        conversion_model=StorageConversionModel(
            model_id="conversion",
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            evidence_ids=("conversion",),
            method_version="test:v1",
        ),
        tariffs=_tariffs_for_schedule_snapshot(),
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )


def test_strategy_observer_closes_every_generated_schedule_through_evaluation() -> None:
    result = _observe()
    schedule_count = len(result.strategy_space.schedules)

    assert schedule_count > 1
    assert len(result.observer_result.portfolio.strategy_results) == schedule_count
    assert len(result.observer_result.candidate_set.candidates) == schedule_count
    assert len(result.observer_result.evaluation.records) == schedule_count
    assert result.observer_only is True
    assert result.selection_permitted is False
    assert result.commitment_permitted is False


def test_strategy_observation_blocks_a_missing_simulated_schedule() -> None:
    result = _observe()
    portfolio = replace(
        result.observer_result.portfolio,
        strategy_results=result.observer_result.portfolio.strategy_results[:-1],
    )
    observer_result = replace(result.observer_result, portfolio=portfolio)

    with pytest.raises(ValueError, match="must be simulated once"):
        replace(result, observer_result=observer_result)


def test_strategy_observer_does_not_import_live_pipeline_or_commitment() -> None:
    from picot.planner import independent_daily_strategy_observer as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
