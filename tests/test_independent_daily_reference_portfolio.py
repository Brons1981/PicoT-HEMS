from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.daily_reference_portfolio import DailyReferencePortfolio
from picot.domain.daily_reference_simulation import (
    DailyReferenceSimulationSet,
    PVScenario,
)
from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.domain.storage_conversion_model import StorageConversionModel
from picot.planner.independent_daily_reference_portfolio import (
    IndependentDailyReferencePortfolioProducer,
)
from test_independent_daily_intent_simulator import _schedule, _simulate, _tariffs
from test_independent_daily_simulator import _household, _storage, _timeline


def _produce() -> DailyReferencePortfolio:
    schedules = tuple(
        _schedule(
            intent,
            export_target_wh=500.0 if intent is DailyStorageIntent.STORAGE_EXPORT else 0.0,
        )
        for intent in DailyStorageIntent
    )
    household = _household()
    tariffs = _tariffs_for_schedule_snapshot()
    return IndependentDailyReferencePortfolioProducer().produce(
        snapshot_id="snapshot-intent",
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
        tariffs=tariffs,
        intent_schedules=schedules,
        minimum_storage_energy_wh=816.0,
        target_storage_energy_wh=8160.0,
        maximum_charge_input_power_w=2400.0,
        maximum_discharge_output_power_w=2400.0,
    )


def _tariffs_for_schedule_snapshot() -> DailyReferenceTariffSchedule:
    sample = _simulate_sample()
    return _tariffs(sample)


def _simulate_sample() -> DailyReferenceSimulationSet:
    return _simulate(DailyStorageIntent.STANDBY)


def test_portfolio_simulates_all_intents_from_one_shared_snapshot() -> None:
    result = _produce()

    assert result.snapshot_id == "snapshot-intent"
    assert result.observer_only is True
    assert result.ranking_permitted is False
    assert len(result.strategy_results) == len(DailyStorageIntent)
    assert {
        item.intent_schedule.intervals[0].intent for item in result.strategy_results
    } == set(DailyStorageIntent)
    assert all(
        item.run.candidate_input_complete for item in result.strategy_results
    )


def test_portfolio_keeps_every_trajectory_tied_to_its_schedule() -> None:
    result = _produce()

    for strategy in result.strategy_results:
        assert all(
            trajectory.intent_schedule_id == strategy.intent_schedule.schedule_id
            for trajectory in strategy.run.simulation.trajectories
        )


def test_portfolio_rejects_mixed_tariff_lineage() -> None:
    result = _produce()
    changed = replace(result.strategy_results[-1].run.financial.paths[0])
    object.__setattr__(changed, "tariff_schedule_id", "different-tariffs")
    financial = replace(
        result.strategy_results[-1].run.financial,
        paths=(changed, *result.strategy_results[-1].run.financial.paths[1:]),
    )
    run = replace(result.strategy_results[-1].run, financial=financial)
    strategy = replace(result.strategy_results[-1], run=run)

    with pytest.raises(ValueError, match="share one tariff schedule"):
        replace(result, strategy_results=(*result.strategy_results[:-1], strategy))


def test_portfolio_producer_does_not_import_current_pipeline() -> None:
    from picot.planner import independent_daily_reference_portfolio as module

    imported_names = set(vars(module))
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
