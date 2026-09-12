"""Regression boundaries between measured-demand inputs and the active planner."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_route_optimisation import fresh
from test_independent_daily_reference_adapter import _snapshot

from picot.domain.daily_reference_charge_window import DailyMainChargeWindowSet
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.household_load_guard import (
    HouseholdLoadGuardAssessment,
    apply_household_load_guard,
)
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_adapter_preserves_exact_projection_end_between_clock_quarters():
    source = _snapshot()
    at = source.captured_at + timedelta(minutes=10)
    assessment = HouseholdLoadGuardAssessment(True, "reliable", 2000.0, at, at)
    baseline = source.household_load_forecast
    source = replace(
        source,
        captured_at=at,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        household_load_guard=assessment,
        household_load_forecast=apply_household_load_guard(baseline, assessment),
    )
    adapter = IndependentDailyReferenceAdapter()
    horizon = at + timedelta(hours=1)
    projected = adapter._inputs(source, horizon_end=horizon).household
    unmodified = adapter._inputs(
        replace(source, household_load_forecast=baseline), horizon_end=horizon,
    ).household
    ends_at = at + timedelta(minutes=15)
    assert any(interval.ends_at == ends_at for interval in projected.intervals)
    extra_wh = 0.0
    for changed, original in zip(projected.intervals, unmodified.intervals, strict=True):
        assert changed.starts_at == original.starts_at
        assert changed.ends_at == original.ends_at
        extra = changed.expected_energy_wh - original.expected_energy_wh
        expected = (
            2000 * (changed.ends_at - changed.starts_at).total_seconds() / 3600
            if changed.ends_at <= ends_at else 0
        )
        assert extra == pytest.approx(expected)
        extra_wh += extra
    assert extra_wh == pytest.approx(500.0)


def test_continuity_candidate_exhaustion_retains_charging_and_exposes_shortfall(
    tmp_path, monkeypatch,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), pv_factor=0, soc=0.7)))
    source = recover(first.planning_input)
    plan = store.load_active_daily_main_plan("battery")
    grid = next(s for s in plan.segments if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    at = grid.starts_at
    source = replace(
        source, captured_at=at,
        current_storage_states=tuple(replace(s, current_soc=0.1, measured_at=at)
                                     for s in source.current_storage_states),
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        daily_charge_context=replace(source.daily_charge_context, restored_at=at),
        household_load_guard=HouseholdLoadGuardAssessment(True, "reliable", 2000.0, at, at),
    )

    def exhausted(self, *, snapshot, assignment, **kwargs):
        return DailyMainChargeWindowSet(
            assignment.assignment_id, snapshot.snapshot_id, (), "unreachable",
            "ongoing_load_requires_committed_grid_continuity", 1,
        )

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", exhausted)
    result = pipeline.run(planning_input=source)
    assert result.evaluation.status == "plan_retained"
    assert result.evaluation.reason == "ongoing_load_requires_committed_grid_continuity"
    assert result.evaluation.daily_main_input_shortfalls
    assert result.primitive_boundary.planned_primitive is ExecutionPrimitive.CHARGE_AT_POWER
    assert store.load_active_daily_main_plan("battery").plan_id == plan.plan_id
    assert all(owner.completed_at is None for owner in store.load_daily_assignments())
