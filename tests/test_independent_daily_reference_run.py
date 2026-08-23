from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_run import DailyReferenceRun
from picot.domain.daily_reference_simulation import PVScenario
from picot.planner.independent_daily_reference_run import (
    IndependentDailyReferenceRunProducer,
)
from test_independent_daily_financial_settlement import _tariffs
from test_independent_daily_simulator import _simulate


def test_run_closes_physical_assessment_and_financial_lineage() -> None:
    simulation = _simulate()
    result = IndependentDailyReferenceRunProducer().produce(
        simulation=simulation,
        tariffs=_tariffs(),
    )

    assert result.simulation is simulation
    assert result.candidate_input_complete is True
    assert result.observer_only is True
    assert result.selection_permitted is False
    assert {item.scenario for item in result.assessment.assessments} == set(PVScenario)
    assert {item.scenario for item in result.financial.paths} == set(PVScenario)


def test_run_rejects_assessment_from_another_simulation() -> None:
    result = IndependentDailyReferenceRunProducer().produce(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )
    changed_assessment = replace(result.assessment)
    object.__setattr__(changed_assessment, "simulation_id", "another-simulation")

    with pytest.raises(ValueError, match="assessment must originate"):
        DailyReferenceRun(
            run_id=result.run_id,
            snapshot_id=result.snapshot_id,
            simulation=result.simulation,
            assessment=changed_assessment,
            financial=result.financial,
            candidate_input_complete=True,
            observer_only=True,
            selection_permitted=False,
            method_version=result.method_version,
        )


def test_run_rejects_financial_path_for_another_trajectory() -> None:
    result = IndependentDailyReferenceRunProducer().produce(
        simulation=_simulate(),
        tariffs=_tariffs(),
    )
    changed_path = replace(result.financial.paths[0])
    object.__setattr__(changed_path, "trajectory_id", "another-trajectory")
    changed_financial = replace(
        result.financial,
        paths=(changed_path, *result.financial.paths[1:]),
    )

    with pytest.raises(ValueError, match="financial trajectory lineage"):
        replace(result, financial=changed_financial)


def test_run_producer_does_not_import_current_pipeline_selection_types() -> None:
    from picot.planner import independent_daily_reference_run as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
