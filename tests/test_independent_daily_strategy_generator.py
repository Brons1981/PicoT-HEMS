from __future__ import annotations

import pytest

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.planner.independent_daily_strategy_generator import (
    IndependentDailyStrategyGenerator,
)
from test_independent_daily_simulator import _household


def test_generator_enumerates_every_requested_window_without_ranking() -> None:
    household = _household()
    result = IndependentDailyStrategyGenerator().generate(
        snapshot_id="snapshot",
        household=household,
        window_lengths_intervals=(1, 2),
    )

    expected_windows_per_intent = len(household.intervals) + len(
        household.intervals
    ) - 1
    assert len(result.schedules) == 1 + 3 * expected_windows_per_intent
    assert result.schedules[0].intervals[0].intent is (
        DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
    )
    assert result.observer_only is True
    assert result.ranking_permitted is False


def test_generator_keeps_active_window_and_baseline_physically_explicit() -> None:
    result = IndependentDailyStrategyGenerator().generate(
        snapshot_id="snapshot",
        household=_household(),
        window_lengths_intervals=(2,),
        active_intents=(DailyStorageIntent.NOM,),
    )
    schedule = result.schedules[2]

    assert schedule.intervals[0].intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
    assert schedule.intervals[1].intent is DailyStorageIntent.NOM
    assert schedule.intervals[2].intent is DailyStorageIntent.NOM
    assert all(
        item.intent is DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY
        for item in schedule.intervals[3:]
    )


def test_generator_requires_explicit_target_for_storage_export() -> None:
    with pytest.raises(ValueError, match="export intent requires an export target"):
        IndependentDailyStrategyGenerator().generate(
            snapshot_id="snapshot",
            household=_household(),
            window_lengths_intervals=(1,),
            active_intents=(DailyStorageIntent.STORAGE_EXPORT,),
        )


def test_generator_adds_bounded_storage_export_windows_when_enabled() -> None:
    result = IndependentDailyStrategyGenerator().generate(
        snapshot_id="snapshot",
        household=_household(),
        window_lengths_intervals=(1,),
        active_intents=(DailyStorageIntent.STORAGE_EXPORT,),
        storage_export_target_wh_per_interval=500.0,
    )

    active = result.schedules[1].intervals[0]
    assert active.intent is DailyStorageIntent.STORAGE_EXPORT
    assert active.storage_export_target_wh == 500.0


def test_generator_does_not_import_current_pipeline_selection_types() -> None:
    from picot.planner import independent_daily_strategy_generator as module

    imported_names = set(vars(module))
    assert "Candidate" not in imported_names
    assert "EvaluationRecord" not in imported_names
    assert "ActivePlanCommitment" not in imported_names
