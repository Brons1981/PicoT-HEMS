"""Validate HEMS outlook for display; it never authorizes heating commands."""
import math
from datetime import datetime

ENTITY = 'sensor.picot_energy_outlook'


def read_outlook(states, now, connected=True):
    empty = dict(status='unavailable', reason='Geen actuele energierichtlijn van HEMS.', slots=[],
                 advisory_only=True, approval_required=True, budgets_additive=False)
    if not connected:
        return dict(empty, reason='HA-verbinding niet actueel.')
    entity = states.get(ENTITY, {})
    value = entity.get('attributes') or {}
    if not isinstance(value, dict) or entity.get('state') in (None, 'unknown', 'unavailable'):
        return empty
    try:
        def instant(text):
            if not isinstance(text, str) or len(text) > 40:
                raise ValueError('time')
            moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if moment.utcoffset() is None:
                raise ValueError('timezone')
            return moment.timestamp()

        def number(x, maximum=1e9):
            if type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= maximum:
                raise ValueError('number')
            return x

        if (value.get('contract') != 'hems-energy-outlook:v1' or value.get('advisory_only') is not True
                or value.get('approval_required') is not True or value.get('budgets_additive') is not False
                or value.get('available_additional_energy_wh') is not None
                or not isinstance(value.get('snapshot_id'), str) or not 1 <= len(value['snapshot_id']) <= 200):
            raise ValueError('contract')
        generated, expires = instant(value['generated_at']), instant(value['valid_until'])
        if not 0 < expires-generated <= 180 or generated > now:
            raise ValueError('validity')
        if now >= expires:
            return dict(empty, status='stale', reason='Energierichtlijn van HEMS verlopen.')
        basis = value.get('replacement_basis')
        replacement = None
        if isinstance(basis, dict) and basis.get('status') == 'ready':
            try:
                start, end = instant(basis['starts_at']), instant(basis['ends_at'])
                identifiers = [basis[k] for k in ('basis_id', 'source_id')]
                if 'modeled_source_id' in basis:
                    if basis.get('attribution') != 'measured_and_reviewed_modeled_subset:v1':
                        raise ValueError('modeled attribution')
                    identifiers.append(basis['modeled_source_id'])
                if (basis.get('execution_authorized') is False
                        and basis.get('demand_basis') == 'replace_controlled_load'
                        and generated <= start < end <= generated+49*3600
                        and all(isinstance(x, str) and len(x) == 64
                                and all(c in '0123456789abcdef' for c in x) for x in identifiers)):
                    replacement = dict(basis, starts_at=start, ends_at=end)
            except (KeyError, ValueError, TypeError, OverflowError):
                pass
        history = value.get('controlled_load_history')
        if isinstance(history, dict) and history.get('active_forecast_corrected') is False:
            if history.get('status') == 'collecting':
                empty['load_history_status'] = 'collecting'
            elif history.get('status') == 'history_ready':
                try:
                    total, residual, controlled = (number(history[k+'_energy_wh'])
                                                   for k in ('total', 'residual', 'controlled'))
                    if abs(total-residual-controlled) < .01:
                        empty['load_history_status'] = 'history_ready'
                except (KeyError, ValueError, TypeError):
                    pass
        if value['status'] == 'blocked':
            return dict(empty, status='blocked', reason='HEMS kan de bestaande energieroute nog niet betrouwbaar beoordelen.')
        if value['status'] != 'ready' or entity['state'] != 'ready':
            raise ValueError('status')
        source = value['slots']
        if not isinstance(source, list) or not 1 <= len(source) <= 24:
            raise ValueError('slots')
        floor = number(value['storage_floor_wh'])
        slots, previous = [], instant(value['horizon_start'])
        if previous != generated:
            raise ValueError('horizon')
        for item in source:
            start, end = instant(item['starts_at']), instant(item['ends_at'])
            if start != previous or end <= start:
                raise ValueError('coverage')
            slot = {k: number(item[k]) for k in ('storage_minimum_wh', 'storage_margin_wh', 'pv_export_wh', 'grid_import_wh')}
            if abs(slot['storage_margin_wh']-max(0, slot['storage_minimum_wh']-floor)) > .002:
                raise ValueError('margin')
            slot.update(starts_at=start, ends_at=end, confidence=number(item['confidence'], 1))
            slots.append(slot)
            previous = end
        if previous != instant(value['horizon_end']) or not now < previous <= generated+49*3600:
            raise ValueError('horizon')
        margin = number(value['projected_minimum_margin_wh'])
        if abs(margin-min(s['storage_margin_wh'] for s in slots)) > .002:
            raise ValueError('summary')
        if replacement is not None:
            empty['replacement_basis'] = replacement
        return dict(empty, status='ready', reason='Verwachting bij de bestaande batterijroute; geen toegekend energiebudget.',
                    generated_at=generated, valid_until=expires, horizon_end=previous, snapshot_id=value['snapshot_id'],
                    projected_minimum_margin_wh=margin, confidence=min(s['confidence'] for s in slots), slots=slots)
    except (KeyError, ValueError, TypeError, OverflowError, AttributeError):
        return dict(empty, status='invalid', reason='Energierichtlijn van HEMS is onvolledig of ongeldig.')
