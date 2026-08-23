from __future__ import annotations

from dataclasses import replace

import pytest

from picot.domain.daily_reference_simulation import PVScenario
from picot.planner.independent_daily_path_assessor import IndependentDailyPathAssessor
from test_independent_daily_simulator import _simulate


def test_assessor_reports_complete_unranked_paths_for_all_scenarios() -> None:
    result = IndependentDailyPathAssessor().assess(_simulate())

    assert result.observer_only is True
    assert result.selection_permitted is False
    assert {item.scenario for item in result.assessments} == set(PVScenario)
    assert all(item.physically_complete for item in result.assessments)
    assert all(item.interval_count == 9 for item in result.assessments)
    assert all(item.target_reached_during_horizon for item in result.assessments)
    assert all(item.reserve_respected for item in result.assessments)


def test_assessor_keeps_target_reached_separate_from_target_held_at_end() -> None:
    simulation = _simulate()
    changed_trajectories = []
    for trajectory in simulation.trajectories:
        last = trajectory.intervals[-1]
        changed_last = replace(
            last,
            usable_pv_wh=0.0,
            pv_to_household_wh=0.0,
            storage_to_household_output_wh=100.0,
            storage_energy_at_end_wh=last.storage_energy_at_end_wh - 100.0,
        )
        changed_trajectories.append(
            replace(trajectory, intervals=(*trajectory.intervals[:-1], changed_last))
        )
    changed_simulation = replace(
        simulation,
        trajectories=tuple(changed_trajectories),
    )

    result = IndependentDailyPathAssessor().assess(changed_simulation)

    for assessment in result.assessments:
        assert assessment.target_reached_during_horizon is True
        assert assessment.target_held_at_horizon_end is False


def test_assessor_totals_reconcile_with_simulated_intervals() -> None:
    simulation = _simulate()
    result = IndependentDailyPathAssessor().assess(simulation)

    for trajectory, assessment in zip(
        simulation.trajectories, result.assessments, strict=True
    ):
        assert assessment.household_demand_wh == pytest.approx(
            sum(item.household_demand_wh for item in trajectory.intervals)
        )
        assert assessment.usable_pv_wh == pytest.approx(
            sum(item.usable_pv_wh for item in trajectory.intervals)
        )
        assert assessment.storage_energy_at_horizon_end_wh == pytest.approx(
            trajectory.intervals[-1].storage_energy_at_end_wh
        )


def test_assessor_rejects_paths_with_different_horizons() -> None:
    simulation = _simulate()
    changed = replace(
        simulation.trajectories[-1],
        horizon_end=simulation.trajectories[-1].horizon_end,
    )
    object.__setattr__(changed, "horizon_end", changed.horizon_end.replace(day=24))
    invalid = replace(
        simulation,
        trajectories=(*simulation.trajectories[:-1], changed),
    )

    with pytest.raises(ValueError, match="share one complete horizon"):
        IndependentDailyPathAssessor().assess(invalid)


def test_assessor_does_not_import_current_evaluation_or_commitment() -> None:
    from picot.planner import independent_daily_path_assessor as assessor_module

    imported_names = set(vars(assessor_module))
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
