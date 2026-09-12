"""Load protection preserves active charging without relaxing the daily target."""

from dataclasses import replace
from datetime import timedelta

from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_daily_main_route_optimisation import fresh

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.daily_charge_assignment import DailyMainShortfallTrigger
from picot.v2.daily_pv_comparison import DailyPVComparison
from picot.v2.household_load_guard import HouseholdLoadGuardAssessment
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def bound_grid(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    initial = recover(fresh(recover(), pv_factor=0.0, soc=0.7, tag="load"))
    result = pipeline.run(planning_input=initial)
    source = recover(result.planning_input)
    plan = store.load_active_daily_main_plan("battery")
    grid = next(s for s in plan.segments if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    at = grid.starts_at
    return replace(
        source,
        captured_at=at,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
        daily_charge_context=replace(source.daily_charge_context, restored_at=at),
        household_load_guard=HouseholdLoadGuardAssessment(True, "reliable", 2000, at, at),
    ), grid


def test_active_charge_not_removed_until_release_or_observed_full(tmp_path, monkeypatch):
    source, grid = bound_grid(tmp_path, monkeypatch)
    owner = source.daily_charge_context.assignments[0]
    adapter = IndependentDailyReferenceAdapter()
    comparison = DailyPVComparison(
        owner.assignment_id,
        "basis",
        "evidence",
        None,
        None,
        "complete",
        1000,
        500,
        900,
        "above_central",
    )
    assert (
        adapter.pv_surplus_trigger(
            snapshot=source,
            assignment=owner,
            comparison=comparison,
            conversion_model=inputs()["conversion_model"],
        )
        is None
    )
    assert adapter._protected_grid_end(source, owner) == grid.ends_at
    unknown = replace(
        source,
        household_load_guard=replace(source.household_load_guard, active=False, quality="unknown"),
    )
    assert adapter._protected_grid_end(unknown, owner) == grid.ends_at
    released = replace(
        source,
        household_load_guard=replace(source.household_load_guard, active=False, extra_power_w=0),
    )
    assert adapter._protected_grid_end(released, owner) is None
    full = replace(
        source,
        current_storage_states=tuple(
            replace(s, current_soc=1.0) for s in source.current_storage_states
        ),
    )
    assert adapter._protected_grid_end(full, owner) is None
    ended = replace(
        source,
        captured_at=grid.ends_at,
        capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=grid.ends_at),
        daily_charge_context=replace(source.daily_charge_context, restored_at=grid.ends_at),
    )
    assert adapter._protected_grid_end(ended, owner) is None


def test_repair_candidates_keep_active_grid_segment(tmp_path, monkeypatch):
    source, grid = bound_grid(tmp_path, monkeypatch)
    source = replace(
        source,
        current_storage_states=tuple(
            replace(s, current_soc=0.1) for s in source.current_storage_states
        ),
    )
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.main_route_shortfalls(snapshot=source, conversion_model=conversion)[0]
    owner = source.daily_charge_context.assignments[0]
    windows = adapter.main_charge_windows(
        snapshot=source, assignment=owner, conversion_model=conversion, optimisation_trigger=trigger
    )
    assert windows.windows
    for window in windows.windows:
        assert all(
            i.intent is DailyStorageIntent.GRID_REQUIREMENT
            for i in window.schedule.intervals
            if i.starts_at < grid.ends_at
        )
        assert window.target_storage_energy_wh == 8160
    assert owner.completed_at is None


def test_small_margin_requires_recoverability_and_expires_before_deadline(tmp_path, monkeypatch):
    source, _ = bound_grid(tmp_path, monkeypatch)
    adapter = IndependentDailyReferenceAdapter()
    owner = source.daily_charge_context.assignments[0]
    conversion = inputs()["conversion_model"]
    trigger = DailyMainShortfallTrigger(
        owner.assignment_id,
        owner.route_plan_id,
        owner.revision,
        owner.route_plan_id,
        source.snapshot_id,
        source.captured_at,
        8140,
        8160,
    )
    # A feasible route is a valid recovery witness; the 20Wh margin never
    # mutates measured SOC or marks the assignment completed.
    healthy = replace(
        source,
        current_storage_states=tuple(
            replace(s, current_soc=0.99) for s in source.current_storage_states
        ),
    )
    assert not adapter.main_repair_required(
        snapshot=healthy, trigger=trigger, conversion_model=conversion
    )
    assert owner.completed_at is None
    assert healthy.current_storage_states[0].current_soc == 0.99
    late_at = max(s.ends_at for s in owner.main_segments) - timedelta(minutes=14)
    late = replace(
        healthy,
        captured_at=late_at,
        capability_snapshot_set=replace(healthy.capability_snapshot_set, captured_at=late_at),
        daily_charge_context=replace(healthy.daily_charge_context, restored_at=late_at),
    )
    assert adapter.main_repair_required(snapshot=late, trigger=trigger, conversion_model=conversion)
    unknown = replace(
        healthy, household_load_guard=replace(healthy.household_load_guard, quality="unknown")
    )
    assert adapter.main_repair_required(
        snapshot=unknown, trigger=trigger, conversion_model=conversion
    )
    large = replace(trigger, projected_main_peak_wh=8000)
    assert adapter.main_repair_required(
        snapshot=healthy, trigger=large, conversion_model=conversion
    )
    # Even a small reported discrepancy cannot postpone action if the live
    # conversion model makes recovery starting later physically impossible.
    slow_conversion = replace(conversion, charge_efficiency=0.01)
    assert adapter.main_repair_required(
        snapshot=source, trigger=trigger, conversion_model=slow_conversion
    )
