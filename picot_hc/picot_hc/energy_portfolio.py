"""Display-only acknowledgement of matching HC proposals. Never executes plans."""
import hashlib
import json
import math
from datetime import datetime

REQUEST_ENTITY = 'sensor.picot_hc_energy_proposals'
RESPONSE_ENTITY = 'sensor.picot_hc_energy_assessment'


def read_assessment(states, now, connected=True):
    empty = dict(status='waiting', selected_plan_id=None, assessments=[], execution_authorized=False,
                 reason='Nog geen HC-energievoorstellen ter beoordeling.')
    if not connected:
        return dict(empty, status='unavailable', reason='HA-verbinding niet actueel.')
    proposal = states.get(REQUEST_ENTITY, {})
    if proposal.get('state') != 'requested':
        return empty
    try:
        request = proposal['attributes']
        entity = states.get(RESPONSE_ENTITY, {})
        answer = entity.get('attributes') or {}
        if entity.get('state') not in ('selected', 'blocked', 'rejected') or entity['state'] != answer.get('status'):
            return dict(empty, reason='Nog geen actuele beoordeling van HEMS.')
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if (answer.get('contract') != 'hc-energy-assessment:v1'
                or answer.get('execution_authorized') is not False
                or any(answer.get(k) != request.get(k) for k in ('request_id', 'revision', 'basis_snapshot_id'))
                or answer.get('request_fingerprint') != digest):
            return dict(empty, reason='Wachten op beoordeling van de actuele voorstellen.')
        if request.get('contract') == 'hc-energy-proposals:v2':
            if (answer.get('replacement_basis_id') != request.get('replacement_basis_id')
                    or answer.get('scope') != 'replacement_demand_on_retained_route'):
                return dict(empty, reason='Wachten op beoordeling met de juiste verbruiksbasis.')
        elif request.get('contract') != 'hc-energy-proposals:v1':
            raise ValueError('contract')
        def instant(value):
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if moment.utcoffset() is None:
                raise ValueError('timezone')
            return moment.timestamp()
        generated = instant(request['generated_at'])
        expiry = min(instant(answer['valid_until']), instant(request['valid_until']))
        if not generated <= now < expiry <= generated+180:
            return dict(empty, status='stale', reason='Beoordeling verlopen; nieuwe voorstellen nodig.')
        rows, candidates = answer.get('assessments', []), {p['plan_id'] for p in request['plans']}
        if not 1 <= len(candidates) <= 5 or not isinstance(rows, list) or len(rows) > 5:
            raise ValueError('plans')
        ids = [row['plan_id'] for row in rows]
        if len(ids) != len(set(ids)) or not set(ids) <= candidates:
            raise ValueError('ids')
        for row in rows:
            if row['status'] == 'feasible':
                value = row['total_incremental_cost_eur']
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('cost')
            elif row['status'] != 'rejected':
                raise ValueError('status')
        selected = answer.get('selected_plan_id')
        status = answer['status']
        if status == 'selected':
            if set(ids) != candidates or not any(r['plan_id'] == selected and r['status'] == 'feasible' for r in rows):
                raise ValueError('selection')
        elif status not in ('blocked', 'rejected') or selected is not None:
            raise ValueError('status')
        reason = {'selected': 'HEMS-advies ontvangen; nog geen uitvoeringsopdracht.',
                            'rejected': 'Geen passend voorstel; HC moet nieuwe voorstellen maken.',
                            'blocked': 'HEMS kan de voorstellen nog niet beoordelen.'}[status]
        if status == 'selected' and answer.get('requires_route_commitment') is True:
            reason = 'HEMS vergelijkt inclusief extra laden; starten wacht op een vastgelegde laadroute.'
        if status == 'blocked':
            reason = {'matching_replacement_basis_required':
                'HEMS wacht op volledig herleidbaar aircoverbruik in dezelfde huisprognose.',
                'replacement_window_not_covered':
                'Het voorstel valt buiten de vervangbare periode; de actuele verbruikscorrectie blijft behouden.',
                'refresh_outlook_and_resubmit':
                'De prognosebasis is verlopen; nieuwe voorstellen op de actuele richtlijn nodig.'}.get(answer.get('reason'), reason)
        return dict(empty, status=status, selected_plan_id=selected, assessments=rows,
                    reason=reason, valid_until=expiry)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return dict(empty, status='invalid', reason='Onvolledige of ongeldige planbeoordeling.')
