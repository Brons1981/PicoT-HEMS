"""Passive evidence for a future building model. No heating decisions."""
from .core import number, observation


def attribute_observation(entity, states, now, attribute, numeric=False):
    result = observation(entity, states, now)
    result.update(attribute=attribute, value=None)
    if result['quality'] != 'available':
        return result
    attrs = states[entity].get('attributes') or {}
    value = attrs.get(attribute)
    if value is None or value in ('unknown', 'unavailable'):
        result['quality'] = 'unknown'
        return result
    if numeric:
        try:
            value = number(value)
        except (TypeError, ValueError):
            result['quality'] = 'invalid'
            return result
        result['unit'] = attrs.get('temperature_unit')
    elif not isinstance(value, str):
        result['quality'] = 'invalid'
        return result
    result['value'] = value
    return result


def building_observation(config, states, now, data, door_entity):
    outdoor = data['outdoor']
    zones = []
    bindings = {}
    for zone in data['zones']:
        indoor = zone['samples']['temperature']
        available = indoor['quality'] == outdoor['quality'] == 'available'
        zones.append(dict(id=zone['id'], delta_t_k=(indoor['value'] - outdoor['value']) if available else None,
                          delta_quality='available' if available else 'missing_input'))
        entity = zone['samples']['device']['entity_id']
        if entity:
            bindings.setdefault(entity, []).append(zone['id'])
    if config.get('cv'):
        bindings[config['cv']] = ['beneden', 'boven']
    sources = []
    for entity, served_zones in bindings.items():
        sources.append(dict(entity_id=entity, zones=served_zones,
                            mode=observation(entity, states, now),
                            activity=attribute_observation(entity, states, now, 'hvac_action'),
                            target=attribute_observation(entity, states, now, 'temperature', True)))
    return dict(version=1, poll_seconds=config['poll_seconds'], zones=zones, sources=sources,
                back_door=observation(door_entity, states, now))
