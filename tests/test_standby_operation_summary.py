from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as N

from picot.v2.plan_narrative import build_plan_narrative


def evidence(*, soc=0.3, projected=True):
    now = datetime(2026, 11, 6, 20, tzinfo=UTC)
    floor = now + timedelta(hours=3)
    charge = now + timedelta(hours=10)
    def segment(start, end, primitive, main=None):
        return N(starts_at=start, ends_at=end, primitive=N(value=primitive),
                 charge_source_policy=None, soc_constraint=N(minimum=0.1),
                 main_assignment_id=main)
    segments = (segment(now, charge, 'balance_discharge_only'),
                segment(charge, charge + timedelta(hours=3), 'balance_bidirectional', 'main'))
    plan = N(valid_until=charge + timedelta(hours=3), segments=segments,
             winning_energy_path_id='chosen', execution_scope_id='battery')
    path = N(path_id='chosen', snapshot_id='snap', projected_import_cost_eur=None,
             projected_export_revenue_eur=None, cost_starts_at=None, projected_states=())
    run = N(planning_input=N(captured_at=now, snapshot_id='snap', daily_charge_context=None,
                            current_storage_states=(N(
                                execution_scope_id='battery', current_soc=soc),)),
            evaluation=N(status='winner_selected'), execution_plan_set=N(plans=(plan,)),
            candidate_set=N(energy_paths=()))
    if projected:
        path.projected_states = (N(at=floor, battery_soc=0.1, flow_starts_at=None),)
        run.candidate_set.energy_paths = (path,)
    return run, now, floor, charge


def test_normal_floor_forecast_is_separate_from_economic_standby():
    run, now, floor, charge = evidence()
    result = build_plan_narrative(run)['operation']
    assert result['floor_status'] == 'projected'
    assert result['minimum_soc_percent'] == 10
    assert result['floor_at'] == floor.isoformat()
    assert result['support_until'] == floor.isoformat()
    assert result['next_charge_at'] == charge.isoformat()


def test_support_until_joins_adjacent_support_segments():
    run, now, floor, _ = evidence()
    plan = run.execution_plan_set.plans[0]
    first, main = plan.segments
    second = N(**vars(first))
    first.ends_at = now + timedelta(minutes=15)
    second.starts_at = first.ends_at
    plan.segments = (first, second, main)
    assert build_plan_narrative(run)['operation']['support_until'] == floor.isoformat()


def test_actual_floor_and_unknown_forecast_are_not_guessed():
    run, now, _, charge = evidence(soc=0.1, projected=False)
    result = build_plan_narrative(run)['operation']
    assert result['floor_status'] == 'reached'
    assert result['floor_at'] == now.isoformat()
    run.planning_input.current_storage_states[0].current_soc = 0.3
    result = build_plan_narrative(run)['operation']
    assert result['floor_status'] == 'unknown'
    assert result['floor_at'] is None
    assert result['next_charge_at'] == charge.isoformat()


def test_scheduled_standby_limits_support_but_is_not_a_floor_claim():
    run, now, floor, charge = evidence()
    support = run.execution_plan_set.plans[0].segments[0]
    standby = N(**vars(support))
    support.ends_at = now + timedelta(hours=1)
    standby.starts_at = support.ends_at
    standby.primitive = N(value='standby')
    run.execution_plan_set.plans[0].segments = (
        support, standby, run.execution_plan_set.plans[0].segments[1])
    result = build_plan_narrative(run)['operation']
    assert result['support_until'] == support.ends_at.isoformat()
    assert result['floor_at'] is None
    assert result['floor_status'] == 'not_projected'
