"""Removed main-grid slots retain NOM in challengers, never in the incumbent."""

from test_daily_main_active_pipeline import setup
from test_daily_pv_route_optimisation import observed, source_with_later_cheap_window

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.planner.independent_daily_intent_simulator import DailyStorageIntent
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_grid_reduction_baseline_preserves_nom_and_exact_incumbent(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    plan = first.execution_plan_set.plans[0]
    snapshot = recover(observed(source, soc=0.90))
    owner = store.load_daily_assignments()[0]
    stored_plan = store.load_daily_main_plan(owner.assignment_id)
    adapter = IndependentDailyReferenceAdapter()
    inputs = adapter._inputs(snapshot, horizon_end=plan.valid_until)
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
            assert proposed.intent is DailyStorageIntent.NOM
        else:
            assert proposed == original
    assert revised_slots
    assert store.load_daily_main_plan(owner.assignment_id) == stored_plan


def test_reduced_winner_keeps_nom_in_every_freed_grid_slot(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    source = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(source))
    old = first.execution_plan_set.plans[0]
    observation = observed(source, soc=0.90)
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
                assert segment.primitive is ExecutionPrimitive.BALANCE_BIDIRECTIONAL
                assert any(s.starts_at <= segment.starts_at and segment.ends_at <= s.ends_at
                           and s.primitive is segment.primitive for s in path.segments)
    assert freed
