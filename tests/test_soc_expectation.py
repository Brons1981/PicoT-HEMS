"""Fresh display expectations cannot select or rewrite a committed route."""
from dataclasses import replace

from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_daily_main_route_optimisation import fresh

from picot.domain.market_plan_binding import MarketPlanBinding
from picot.v2.soc_expectation import committed_soc_expectation


def test_retained_expectation_uses_fresh_soc_without_changing_plan(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    run = pipeline.run(planning_input=source)
    plan = store.load_active_daily_main_plan(run.execution_plan_set.plans[0].execution_scope_id)
    saved = (tmp_path / 'plans.json').read_bytes()
    snapshot = recover(fresh(source, soc=0.65))
    def forbidden(*args, **kwargs):
        raise AssertionError('forecast must not plan')
    monkeypatch.setattr(pipeline, 'run', forbidden)
    patch = committed_soc_expectation(snapshot, plan, inputs()['conversion_model'])
    assert patch['soc_timeline'], patch['soc_expectation'].get('reason')
    assert patch['soc_timeline'][0]['soc_percent'] == 65
    assert patch['soc_timeline'][0]['at'] == snapshot.captured_at.isoformat()
    assert len(patch['soc_timeline']) > 2
    assert patch['soc_expectation']['snapshot_id'] == snapshot.snapshot_id
    assert patch['soc_expectation']['plan_id'] == plan.plan_id
    assert patch['chosen_plan']['energy_path_id'] == plan.winning_energy_path_id
    assert patch['soc_projection_retained'] is False
    assert (tmp_path / 'plans.json').read_bytes() == saved
    assert store.load_active_daily_main_plan(plan.execution_scope_id) == plan
    lower = committed_soc_expectation(recover(fresh(source, soc=0.45)), plan,
                                      inputs()['conversion_model'])
    assert lower['soc_timeline'][1]['soc_percent'] < patch['soc_timeline'][1]['soc_percent']


def test_missing_inputs_fail_closed_without_stale_future(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    plan = pipeline.run(planning_input=source).execution_plan_set.plans[0]
    patch = committed_soc_expectation(replace(recover(), pv_energy_timeline=None), plan,
                                      inputs()['conversion_model'])
    assert patch['soc_timeline'] == []
    assert patch['soc_expectation']['status'] == 'unavailable'


def test_active_composite_plan_keeps_original_assignment_owner(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    run = pipeline.run(planning_input=source)
    original = store.load_active_daily_main_plan(run.execution_plan_set.plans[0].execution_scope_id)
    snapshot = recover(fresh(source, soc=0.55))
    composite = replace(original, plan_id='composite-active-route')
    snapshot = replace(snapshot, daily_charge_context=replace(
        snapshot.daily_charge_context,
        main_plans=(*snapshot.daily_charge_context.main_plans, composite),
        active_main_plan_ids=(composite.plan_id,),
        market_plan_bindings=(MarketPlanBinding(
            assignment_id='market-owner', execution_scope_id=composite.execution_scope_id,
            plan_id=composite.plan_id, snapshot_id=snapshot.snapshot_id,
            segment_ids=(composite.segments[-1].segment_id,), expected_export_wh=100,
            segment_export_wh=(100,),
        ),),
    ))
    patch = committed_soc_expectation(snapshot, composite, inputs()['conversion_model'])
    assert patch['soc_expectation']['status'] == 'available', patch['soc_expectation']
    assert patch['soc_timeline'][0]['soc_percent'] == 55
    assert patch['chosen_plan']['plan_id'] == composite.plan_id
