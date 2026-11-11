"""Read-only evidence for the actual heating decision, never a second planner."""
import copy

from .control import numeric
from .energy_outlook import read_outlook


def explain(heating, config, plan, now):
    inputs = plan['decision_inputs']
    room = plan['zones']['beneden']
    control = heating.control
    records = {c['id']: c for c in control.records()}
    selected = [s for s in ('beneden', 'cv') if s in plan['desired']]
    basis = inputs['basis']
    if not plan['enabled']:
        basis = 'disabled'
    elif not selected:
        basis = 'no_demand' if not room['demand'] else 'blocked'
    thermostat = plan['sources']['cv']
    thermostat_temp = thermostat.get('current_temperature') if thermostat['available'] else None
    room_temp = room['temperature']
    execution = {}
    for source in ('beneden', 'cv'):
        item = plan['sources'][source]
        own = heating.data['owned'].get(source, {})
        command = records.get(own.get('command'), {})
        execution[source] = dict(mode=item['state'], available=item['available'],
            target_c=item['temperature'], activity=item.get('action'),
            pending=item['pending'], fault=heating.data['faults'].get(source),
            command_status=command.get('status'), command_value=command.get('value'),
            command_field=command.get('field'),
            conflicts=heating.conflicting_sources(plan, source, records),
            restart_wait_seconds=max(0, 180-(now-heating.data['changed'].get(source, -1e20)))
                if not own or own.get('standby') else 0)
    fresh = bool(control.connected and control.received is not None
                 and 0 <= now-control.received <= config['stale_seconds'])
    outlook = read_outlook(control.states, now, fresh)
    settings = heating.data['settings']
    cv_cost = plan['costs']['cv']
    return copy.deepcopy(dict(
        evaluated_at=now, basis=basis, selected=selected,
        room_temperature_c=room_temp, room_target_c=room['target'], room_reason=room['reason'],
        room_sensor=next(z['temperature'] for z in config['zones'] if z['id'] == 'beneden'),
        thermostat_temperature_c=thermostat_temp,
        temperature_difference_c=thermostat_temp-room_temp
            if numeric(thermostat_temp) is not None and numeric(room_temp) is not None else None,
        prices=inputs['prices'], costs=plan['costs'], candidates=inputs['candidates'],
        assumptions={k: settings[k] for k in ('cop_beneden', 'cop_boven', 'cv_efficiency', 'gas_kwh_m3')},
        electricity_break_even_eur_kwh=cv_cost*settings['cop_beneden'] if cv_cost is not None else None,
        execution=execution, hems_advice=dict(status=outlook['status'], reason=outlook['reason']),
        start_plan=plan.get('energy_start'),
        estimate=True, cost_scope='current_unit_heat_cost',
    ))
