"""Read-only export of stored control evidence; never export credentials."""
import copy
import time

from . import __version__
from .control import DOWNSTAIRS_FAN


def collect(runtime):
    with runtime.control.lock:
        control = runtime.control
        entities = {binding['entity_id'] for binding in control.bindings.values()}
        entities.add(DOWNSTAIRS_FAN)
        states = {}
        for entity in sorted(entities):
            item = control.states.get(entity, {})
            attrs = item.get('attributes') or {}
            states[entity] = {key: item.get(key) for key in
                              ('state', 'last_updated', 'last_changed', 'last_reported')}
            states[entity]['attributes'] = {key: attrs.get(key) for key in
                ('temperature', 'hvac_action', 'hvac_modes', 'target_temp_step', 'options')}
        learning_models = {}
        for name, model in (("warmup", getattr(runtime, 'warmup_energy', None)),
                            ("startup", getattr(getattr(runtime, 'startup_energy', None), 'model', None)),
                            ("maintenance", getattr(getattr(runtime, 'energy_proposals', None), 'model', None))):
            if model is not None:
                learning_models[name] = dict(records=model.records,
                    events=getattr(model, 'events', []), attempted=getattr(model, 'attempted', []))
        cooling = getattr(getattr(runtime.heating, 'learning', None), 'cooling', None)
        if cooling is not None:
            learning_models['cooling'] = dict(records=cooling.samples, segment=cooling.segment)
        return copy.deepcopy(dict(
            format='picot_hc_control_diagnostics', version=1, hc_version=__version__,
            exported_at=time.time(), timezone='Europe/Amsterdam',
            command_timeout_seconds=control.timeout,
            poll_seconds=runtime.config['poll_seconds'],
            stale_seconds=runtime.config['stale_seconds'],
            connected=control.connected, last_received=control.received,
            commands=control.records(), heating=runtime.heating.data,
            schedule=runtime.schedule.data, door_fan=runtime.heating.door_fan.data,
            reported_states=states, learning_models=learning_models,
            strategy_readiness=getattr(runtime, 'strategy_readiness', None),
        ))
