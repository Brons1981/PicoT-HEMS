"""Released grid slots capture actual forecast surplus and preserve incumbent lineage."""

from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_pv_route_optimisation import observed, source_with_later_cheap_window

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.independent_daily_intent_simulator import DailyStorageIntent
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.zendure_mode_capabilities import ZendureModeCapabilityEvidence


@pytest.mark.parametrize("basis,nom", [("lower", False), ("mean-lower-central", False),
                                      ("central", True), ("upper", True)])
def test_grid_reduction_baseline_uses_pv_surplus_and_exact_incumbent(
    tmp_path, monkeypatch, basis, nom,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    plan = first.execution_plan_set.plans[0]
    snapshot = recover(observed(source, soc=0.90))
    owner = store.load_daily_assignments()[0]
    stored_plan = store.load_daily_main_plan(owner.assignment_id)
    adapter = IndependentDailyReferenceAdapter()
    inputs = adapter._inputs(snapshot, horizon_end=plan.valid_until)
    inputs = replace(inputs,
        household=replace(inputs.household, intervals=tuple(
            replace(i, expected_energy_wh=100, battery_excluded_energy_wh=90)
            for i in inputs.household.intervals)),
        pv_scenarios=tuple(replace(s, planning_basis=basis, timeline=replace(
            s.timeline, intervals=tuple(replace(i, energy_wh={
                "lower": 50, "central": 150, "upper": 250,
            }[s.scenario.value]) for i in s.timeline.intervals))) for s in inputs.pv_scenarios))
    incumbent, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
    )
    challenger, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
        revising_assignment_id=owner.assignment_id,
    )
    grid = tuple(s for s in plan.segments
                 if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
                 and s.main_assignment_id == owner.assignment_id)
    assert grid
    revised_slots = 0
    for original, proposed in zip(incumbent.intervals, challenger.intervals, strict=True):
        if any(s.starts_at <= original.starts_at and original.ends_at <= s.ends_at for s in grid):
            revised_slots += 1
            assert original.intent is DailyStorageIntent.GRID_REQUIREMENT
            assert proposed.intent is (DailyStorageIntent.NOM if nom
                                       else DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY)
        else:
            assert proposed == original
    assert revised_slots
    assert store.load_daily_main_plan(owner.assignment_id) == stored_plan


def test_reduced_winner_uses_discharge_only_in_freed_zero_pv_slots(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    old = first.execution_plan_set.plans[0]
    observation = observed(source, soc=0.76)
    result = pipeline.run(planning_input=recover(observation))
    assert result.evaluation.daily_pv_surplus_trigger is not None
    plan = result.execution_plan_set.plans[0]
    path = next(p for p in result.candidate_set.energy_paths
                if p.path_id == result.evaluation.winning_energy_path_id)
    freed = []
    for previous in old.segments:
        if previous.primitive is not ExecutionPrimitive.CHARGE_AT_POWER:
            continue
        for segment in plan.segments:
            if (segment.starts_at < previous.ends_at and previous.starts_at < segment.ends_at
                    and segment.primitive is not ExecutionPrimitive.CHARGE_AT_POWER):
                freed.append(segment)
                assert all(i.pv_energy_wh == 0 for i in observation.pv_energy_timeline.intervals
                           if i.starts_at < segment.ends_at and segment.starts_at < i.ends_at)
                assert segment.primitive is ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
                assert any(s.starts_at <= segment.starts_at and segment.ends_at <= s.ends_at
                           and s.primitive is segment.primitive for s in path.segments)
    assert freed


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("primitive", [ExecutionPrimitive.STANDBY,
                                      ExecutionPrimitive.CHARGE_AT_POWER])
@pytest.mark.parametrize("pv_wh,expected", [
    (0, DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY),
    (100, DailyStorageIntent.HOUSEHOLD_SUPPORT_ONLY),
    (150, DailyStorageIntent.NOM),
])
def test_released_free_bridge_requires_pv_surplus(
    tmp_path, monkeypatch, primitive, pv_wh, expected, running,
):
    """A released bridge is not evidence for PV; exact incumbent stays unchanged."""
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    pipeline.run(planning_input=recover(source))
    owner = store.load_daily_assignments()[0]
    plan = store.load_daily_main_plan(owner.assignment_id)
    snapshot = recover(observed(source, soc=0.9))
    snapshot = replace(snapshot, storage_mode_capability_evidence=ZendureModeCapabilityEvidence(
        captured_at=snapshot.captured_at, source_entity_id="select.battery",
        capability_id="storage-capability", execution_scope_id="battery",
        current_vendor_mode="Snel opladen" if running else "Alleen slim ontladen",
        status="available", unavailable_reason=None, usable_vendor_modes=(),
        excluded_dynamic_vendor_modes=(), mappings=()))
    free = next(s for s in plan.segments if s.main_assignment_id is None
                and s.ends_at > snapshot.captured_at)
    bridge = replace(free, primitive=primitive, purpose=f"bridge:{owner.assignment_id}",
                     requested_power_w=2400 if primitive is ExecutionPrimitive.CHARGE_AT_POWER
                     else None, charge_source_policy=None)
    revised_plan = replace(plan, segments=tuple(
        bridge if s.segment_id == free.segment_id else s for s in plan.segments))
    snapshot = replace(snapshot, daily_charge_context=replace(
        snapshot.daily_charge_context, main_plans=(revised_plan,)))
    adapter = IndependentDailyReferenceAdapter()
    inputs = adapter._inputs(snapshot, horizon_end=plan.valid_until)
    inputs = replace(inputs,
        household=replace(inputs.household, intervals=tuple(
            replace(i, expected_energy_wh=100, battery_excluded_energy_wh=90)
            for i in inputs.household.intervals)),
        pv_scenarios=tuple(replace(s, timeline=replace(s.timeline, intervals=tuple(
            replace(i, energy_wh=pv_wh) for i in s.timeline.intervals)))
            for s in inputs.pv_scenarios))
    before = store._path.read_bytes()
    incumbent, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None)
    challenger, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=inputs, supplied=None,
        revising_assignment_id=owner.assignment_id)
    checked = 0
    for old, new in zip(incumbent.intervals, challenger.intervals, strict=True):
        if bridge.starts_at <= old.starts_at and old.ends_at <= bridge.ends_at:
            checked += 1
            assert old.intent is (DailyStorageIntent.STANDBY
                                  if primitive is ExecutionPrimitive.STANDBY
                                  else DailyStorageIntent.GRID_REQUIREMENT)
            assert new.intent is (old.intent if running else expected)
    assert checked
    assert store._path.read_bytes() == before
