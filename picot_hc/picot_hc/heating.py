"""Opt-in feedback-controlled heating. Prices and efficiencies are estimates."""
import copy
import json
import math
import time
import uuid
from datetime import datetime

from .control import PENDING, numeric
from .core import observation, prices, tariff_confirmed, timestamp
from .schedule import TZ

DEFAULTS = dict(enabled=False, cv_efficiency=.90, gas_kwh_m3=35.17/3.6,
                cop_beneden=3.72, cop_boven=3.0)
COVERAGE = {'cv': ['beneden', 'boven'], 'beneden': ['beneden'],
            'boven': ['boven'], 'badkamer': ['badkamer']}
FAILURES = {'failed', 'timed_out', 'interrupted'}


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULTS) or type(settings['enabled']) is not bool:
        raise ValueError('Ongeldige instellingen voor automatische verwarming.')
    for key, low, high in [('cv_efficiency', .5, 1), ('gas_kwh_m3', 8, 13),
                           ('cop_beneden', 1, 8), ('cop_boven', 1, 8)]:
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Ongeldige rendementsaanname: ' + key)
    return copy.deepcopy(settings)


class Heating:
    # All runtime entry points use Control.lock, including fresh-read guards.
    def __init__(self, control, schedule, store):
        self.control, self.schedule, self.store = control, schedule, store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_heating (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_heating WHERE id=1').fetchone()
        self.data = json.loads(row[0]) if row else dict(settings=copy.deepcopy(DEFAULTS), revision=0,
            owned={}, faults={}, demand={}, changed={})
        self.data.setdefault('manual', [])
        self.data.setdefault('timer_revision', 0)
        self.data.setdefault('timer', None)
        self.armed = False
        if self.data['timer'] and self.data['timer']['status'] == 'running':
            self.data['timer']['status'] = 'restart'
            self.data['timer_revision'] += 1
            self.save()
        if self.data['settings']['enabled']:
            self.data['settings']['enabled'] = False
            self.data['revision'] += 1
            self.save()

    def save(self):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_heating VALUES (1, ?)',
                       (json.dumps(self.data, allow_nan=False),))

    def update(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'revision', 'settings'}
                or type(payload['revision']) is not int or payload['revision'] != self.data['revision']):
            raise ValueError('Instellingen gewijzigd; herlaad het dashboard.')
        settings = validate_settings(payload['settings'])
        previous = copy.deepcopy(self.data)
        self.data.update(settings=settings, revision=self.data['revision']+1)
        if not settings['enabled'] and self.data['timer'] and self.data['timer']['status'] == 'running':
            self.data['timer']['status'] = 'stopped'
            self.data['timer_revision'] += 1
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        self.armed = True

    def reset_faults(self):
        previous = copy.deepcopy(self.data)
        self.data['faults'] = {}
        records = {c['id']: c for c in self.control.records()}
        for own in self.data['owned'].values():
            command = records.get(own['command'])
            if not command or command['status'] in FAILURES:
                own['retry_stop'] = True
        try:
            self.save()
        except Exception:
            self.data = previous
            raise

    def timer_active(self, now):
        timer = self.data['timer']
        return bool(timer and timer['status'] == 'running' and now < timer['ends'])

    def update_timer(self, payload, config, now):
        if (not isinstance(payload, dict) or type(payload.get('revision')) is not int
                or payload['revision'] != self.data['timer_revision']):
            raise ValueError('Timer gewijzigd; herlaad het dashboard.')
        action = payload.get('action')
        previous = copy.deepcopy(self.data)
        if action == 'start' and set(payload) == {'revision', 'action', 'minutes', 'temperature'}:
            minutes, target = payload['minutes'], payload['temperature']
            zone = next(z for z in config['zones'] if z['id'] == 'badkamer')
            low, high = numeric(zone.get('minimum')), numeric(zone.get('maximum'))
            if type(minutes) is not int or not 1 <= minutes <= 180:
                raise ValueError('Kies 1 tot en met 180 hele minuten.')
            if (type(target) not in (int, float) or not math.isfinite(target) or not 5 <= target <= 35
                    or low is None or high is None or not low <= target <= high):
                raise ValueError('Kies een temperatuur binnen de ingestelde badkamergrenzen.')
            self.data['timer'] = dict(minutes=minutes, temperature=target, ends=now+60*minutes, status='running', cleanup=True)
        elif action == 'stop' and set(payload) == {'revision', 'action'}:
            if self.data['timer']:
                self.data['timer']['status'] = 'stopped'
        else:
            raise ValueError('Ongeldig timerverzoek.')
        self.data['timer_revision'] += 1
        try:
            self.save()
        except Exception:
            self.data = previous
            raise

    def reconcile(self, now):
        records = {c['id']: c for c in self.control.records()}
        holds = {h['source'] for h in self.schedule.view(now)['overrides'] if h['active']}
        timer = self.data['timer']
        if timer and timer['status'] == 'running' and (now >= timer['ends'] or 'badkamer' in holds):
            timer['status'] = 'manual' if 'badkamer' in holds else 'expired'
            self.data['timer_revision'] += 1
        for source in holds:
            if source not in self.data['manual']:
                self.data['manual'].append(source)
        if self.data['settings']['enabled']:
            for source in list(self.data['manual']):
                if source not in holds:
                    # Expired hold / explicit HC resume releases this source to the regulator.
                    self.data['owned'][source] = dict(command=None, since=now, released=True)
                    self.data['manual'].remove(source)
        for source, own in list(self.data['owned'].items()):
            if source in holds:
                del self.data['owned'][source]  # Respect manual takeover, including manual Off.
                continue
            command = records.get(own['command'])
            if own.get('released') or own.get('retry_stop'):
                continue
            if not command or command['status'] in FAILURES:
                self.data['faults'][source] = (command or {}).get('error') or 'Opdracht niet bevestigd; controleer bron.'
            elif command['value'] == 'off' and command['status'] in ('confirmed', 'already_set'):
                self.data['changed'][source] = now
                del self.data['owned'][source]
        if timer and not self.timer_active(now) and (
                'badkamer' not in self.data['owned'] or self.armed and self.data['settings']['enabled']):
            timer['cleanup'] = False

    def plan(self, config, now):
        settings = self.data['settings']
        view = self.schedule.view(now)
        sources = {s['id']: s for s in self.control.sources(now, config['stale_seconds'])}
        owned = self.data['owned']
        records = {c['id']: c for c in self.control.records()}
        holds = [h for h in view['overrides'] if h['active']]
        blocked = {z for h in holds for z in h['zones']}
        # Existing manual heat/dry/cool and unconfirmed manual writes retain authority.
        for source, item in sources.items():
            if source not in owned and (item['state'] not in ('off', None, 'unknown', 'unavailable') or item['pending']):
                blocked.update(COVERAGE[source])
        if view['legacy_pause']:
            blocked.update(('beneden', 'boven'))
        zones, demand = {}, {}
        fresh = (self.control.connected and self.control.received is not None
                 and 0 <= now-self.control.received <= config['stale_seconds'])
        for zone in config['zones']:
            zid = zone['id']
            req = view['comfort']['zones'][zid]
            goal = req['request']
            if zid == 'badkamer' and self.timer_active(now):
                goal = {'target': self.data['timer']['temperature']}
            sample = observation(zone['temperature'], self.control.states, now, True, '°C')
            temp = sample['value']
            reason = None
            try:
                age = now-timestamp(sample.get('source_reported') or sample.get('source_updated'))
            except (ValueError, TypeError, OverflowError):
                age = None
            if not fresh or sample['quality'] != 'available' or age is None or not 0 <= age <= view['settings']['sensor_max_age_seconds']:
                reason = 'Temperatuur ontbreekt of brontijd is te oud.'
            elif not goal or numeric(goal.get('target')) is None or not 5 <= goal['target'] <= 35:
                reason = 'Geen bruikbaar temperatuurdoel ingesteld.'
            elif req['errors']:
                reason = ' '.join(req['errors'])
            elif zid == 'badkamer' and self.timer_active(now) and (
                    numeric(zone.get('minimum')) is None or numeric(zone.get('maximum')) is None
                    or not zone['minimum'] <= goal['target'] <= zone['maximum']):
                reason = 'Timerdoel valt buiten de badkamergrenzen.'
            elif zid in blocked:
                reason = 'Handmatige bronkeuze heeft voorrang.'
            target = goal['target'] if goal else None
            on = False
            if reason is None:
                on = temp < target if self.data['demand'].get(zid) else temp <= target-.3
            demand[zid] = on
            zones[zid] = dict(temperature=temp, target=target, demand=on, reason=reason or
                              ('Warmtevraag.' if on else 'Temperatuur bereikt; geen warmtevraag.'))
        rows, warnings = prices(self.control.states.get(config['price_entity']), config, now)
        price = next((p['value'] for p in rows if p['start'] <= now < p['end']), None)
        if not tariff_confirmed(config) or warnings:
            price = None
        gas = numeric(config.get('gas_price'))
        try:
            gas_valid = datetime.fromtimestamp(now, TZ).date() <= datetime.strptime(config['gas_valid_until'], '%Y-%m-%d').date()
        except (ValueError, TypeError, KeyError):
            gas_valid = False
        costs = {z: price/settings['cop_'+z] if price is not None else None for z in ('beneden', 'boven')}
        costs['badkamer'] = price
        costs['cv'] = gas/(settings['gas_kwh_m3']*settings['cv_efficiency']) if gas is not None and gas >= 0 and gas_valid else None
        door = view['door'] or {'value': 'unknown', 'since': now}
        elapsed = now-door['since']
        door_start = door['value'] == 'off' and elapsed >= view['settings']['door_close_seconds']
        door_stop = (door['value'] == 'unknown' or
                     door['value'] == 'on' and elapsed >= view['settings']['door_open_seconds'])

        def eligible(source, target):
            s = sources[source]
            if not s['available'] or source in self.data['faults'] or any(z in blocked for z in COVERAGE[source]):
                return False
            if source == 'badkamer':
                return True
            if not s['temperature_supported'] or 'heat' not in s['modes'] or 'off' not in s['modes']:
                return False
            steps = (target-s['minimum'])/s['step']
            return s['minimum'] <= target <= s['maximum'] and math.isclose(steps, round(steps), abs_tol=.00001)

        desired = {}
        enabled = settings['enabled'] and self.armed
        if enabled and price is not None:
            for zid in ('beneden', 'boven', 'badkamer'):
                target = zones[zid]['target']
                if demand[zid] and eligible(zid, target):
                    if zid == 'beneden' and not (door_start or zid in owned and not door_stop):
                        zones[zid]['reason'] = 'Airco wacht op gesloten achterdeur en herstelvertraging.'
                    else:
                        desired[zid] = target
            down, up = zones['beneden'], zones['boven']
            # The room thermostat is downstairs: it cannot independently heat upstairs.
            cv_ok = (demand['beneden'] and up['reason'] in ('Warmtevraag.', 'Temperatuur bereikt; geen warmtevraag.')
                     and up['temperature'] < up['target'] and eligible('cv', down['target'])
                     and costs['cv'] is not None)
            if cv_ok and all(z not in desired or costs['cv'] < costs[z] for z in ('beneden', 'boven') if demand[z]):
                desired.pop('beneden', None)
                desired.pop('boven', None)
                desired['cv'] = down['target']
            # Keep a viable incumbent for five minutes before an economic switch.
            for source, own in owned.items():
                c = records.get(own['command'], {})
                if own.get('released') or c.get('value') == 'off' or source in desired or now-own['since'] >= 300:
                    continue
                viable = (cv_ok if source == 'cv' else demand[source] and eligible(source, zones[source]['target'])
                          and (source != 'beneden' or not door_stop))
                if viable:
                    for other in list(desired):
                        if set(COVERAGE[source]) & set(COVERAGE[other]):
                            del desired[other]
                    desired[source] = zones['beneden' if source == 'cv' else source]['target']
        # An explicit bathroom timer needs no economic source selection or global enable.
        if self.timer_active(now) and demand['badkamer'] and eligible('badkamer', zones['badkamer']['target']):
            desired['badkamer'] = zones['badkamer']['target']
        for zid, zone in zones.items():
            timed = zid == 'badkamer' and self.timer_active(now)
            if not enabled and not timed:
                zone['reason'] = 'Automatische verwarming staat uit.'
            elif zone['demand'] and price is None and not timed:
                zone['reason'] = 'Geen bevestigd huidig stroomtarief; bronkeuze geblokkeerd.'
            elif zone['demand'] and not any(zid in COVERAGE[s] for s in desired) and zone['reason'] == 'Warmtevraag.':
                zone['reason'] = 'Warmtevraag; bron geblokkeerd door mogelijkheden, storing of gedeelde cv-grens.'
        return dict(desired=desired, zones=zones, demand=demand, costs=costs, price=price,
                    door_stop=door_stop, sources=sources, enabled=enabled,
                    estimate=True, strategy='current_heat_cost', preheating=False, learning=False)

    def action(self, plan, now):
        records = {c['id']: c for c in self.control.records()}
        holds = {h['source'] for h in self.schedule.view(now)['overrides'] if h['active']}
        # Stop obsolete owned sources before any new start. Stop can preempt a start.
        for source, own in self.data['owned'].items():
            if not self.armed and source != 'badkamer':
                continue
            if source in holds:
                continue
            c = records.get(own['command'], {})
            if c.get('value') == 'off' and not own.get('retry_stop'):
                continue  # Includes failed/uncertain stops: never replay automatically.
            if source not in plan['desired'] and plan['sources'][source]['available']:
                return source, 'state' if source == 'badkamer' else 'mode', 'off'
        for source, target in plan['desired'].items():
            s = plan['sources'][source]
            if s['pending'] or source in self.data['faults']:
                continue
            conflict = any(other != source and set(COVERAGE[source]) & set(COVERAGE[other])
                           for other in self.data['owned'])
            if conflict:
                continue
            if source not in self.data['owned'] and now-self.data['changed'].get(source, -1e20) < 180:
                continue
            if source == 'badkamer':
                if s['state'] != 'on':
                    return source, 'state', 'on'
            elif s['state'] != 'heat' or not self.control.matches(s['temperature'], target):
                return source, 'heating', target
        return None

    def tick(self, config, now=None):
        now = time.time() if now is None else now
        if not self.armed and not (self.data['timer'] or {}).get('cleanup'):
            return
        self.reconcile(now)
        plan = self.plan(config, now)
        self.data['demand'] = plan['demand']
        self.save()  # Storage failure must precede all device writes.
        # One write per poll, prioritising stops; remaining independent sources follow.
        chosen = self.action(plan, now)
        if chosen is None:
            return
        source, field, value = chosen
        request_id = str(uuid.uuid4())

        def guard():
            moment = time.time()
            self.reconcile(moment)
            current = self.plan(config, moment)
            if self.action(current, moment) != chosen:
                raise ValueError('Regelbesluit veranderd na verse HA-uitlezing; geen opdracht.')
            previous = copy.deepcopy(self.data)
            self.data['owned'][source] = dict(command=request_id,
                since=self.data['owned'].get(source, {}).get('since', moment))
            self.data['changed'][source] = moment
            try:
                self.save()
            except Exception:
                self.data = previous
                raise

        try:
            self.control.submit(dict(request_id=request_id, source=source, field=field, value=value),
                                config['stale_seconds'], origin='schedule', guard=guard, force_off=value == 'off')
        except ValueError:
            # Fresh-read guard or capability change. No retries of recorded commands.
            return

    def view(self, config, now):
        result = self.plan(config, now)
        result.update(settings=copy.deepcopy(self.data['settings']), revision=self.data['revision'],
                      faults=copy.deepcopy(self.data['faults']), owned=copy.deepcopy(self.data['owned']))
        timer = copy.deepcopy(self.data['timer'])
        result['timer'] = dict(revision=self.data['timer_revision'], active=self.timer_active(now),
            remaining_seconds=max(0, timer['ends']-now) if self.timer_active(now) else 0,
            **(timer or dict(minutes=30, temperature=22, ends=None, status='idle')))
        return result
