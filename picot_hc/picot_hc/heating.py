"""Opt-in feedback-controlled heating. Prices and efficiencies are estimates."""
import copy
import json
import math
import time
import uuid
from datetime import datetime

from .control import PENDING, numeric
from .cv_state import passive_idle
from .core import observation, prices, tariff_confirmed, timestamp
from .schedule import TZ
from .learning import Learning
from .door_fan import DoorFan

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
        self.learning = Learning(store)
        self.energy_start = None
        # Persist the user's choice; fresh source/measurement checks still gate writes.
        self.armed = bool(self.data['settings']['enabled'])
        self.data.setdefault('missing_data_since', {})
        self.door_fan = DoorFan(self)
        if self.data['timer'] and self.data['timer']['status'] == 'running':
            self.data['timer']['status'] = 'restart'
            self.data['timer_revision'] += 1
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
        # Fresh confirmation of the latest intent, including a protective stop,
        # clears a historical fault without resending commands or releasing holds.
        received = self.control.received
        if (self.control.connected and received is not None
                and 0 <= now-received <= self.schedule.config['stale_seconds']):
            for source in list(self.data['faults']):
                entity = self.control.bindings[source]['entity_id']
                command = next((c for c in records.values() if c['entity_id'] == entity), None)
                item = self.control.states.get(entity, {})
                if (not command or command['status'] not in ('confirmed', 'already_set')
                        or item.get('state') in (None, 'unknown', 'unavailable')
                        or received < command.get('finished', now)):
                    continue
                actual = (item.get('attributes', {}).get('temperature')
                          if command['field'] in ('temperature', 'heating') else item['state'])
                if (self.control.matches(actual, command['value'])
                        and (command['field'] != 'heating' or item['state'] == 'heat')):
                    del self.data['faults'][source]
                    self.data.setdefault('fault_recoveries', {})[source] = dict(
                        at=now, command=command['id'], reason='latest_intent_confirmed')
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
            if (own.get('released') and not own.get('standby')) or own.get('retry_stop'):
                continue
            if not command or command['status'] in FAILURES:
                self.data['faults'][source] = (command or {}).get('error') or 'Opdracht niet bevestigd; controleer bron.'
            elif command['value'] == 'off' and command['status'] in ('confirmed', 'already_set'):
                self.data['changed'][source] = now
                del self.data['owned'][source]
        if timer and not self.timer_active(now) and (
                'badkamer' not in self.data['owned'] or self.armed and self.data['settings']['enabled']):
            timer['cleanup'] = False

    def learning_context(self, config, view, now, blocked):
        from .thermal_weather import observed
        zone = next(z for z in config['zones'] if z['id'] == 'beneden')
        def temperature(entity):
            sample = observation(entity, self.control.states, now, True, '°C')
            try:
                age = now-timestamp(sample.get('source_reported') or sample.get('source_updated'))
            except (TypeError, ValueError, OverflowError):
                return None
            return sample['value'] if (sample['quality'] == 'available' and not sample.get('report_error')
                and 0 <= age <= view['settings']['sensor_max_age_seconds']) else None
        indoor, outdoor = temperature(zone['temperature']), temperature(config['outdoor'])
        door = view['door'] or {}
        sources = {s['id']: s for s in self.control.sources(now, config['stale_seconds'])}
        cv = sources['cv']
        cv_inactive = (cv['available'] and not cv['pending']
                       and (cv['state'] == 'off' or passive_idle(cv)))
        valid = (self.control.connected and self.control.received is not None
                 and 0 <= now-self.control.received <= config['stale_seconds']
                 and indoor is not None and outdoor is not None and 'beneden' not in blocked
                 and door.get('value') == 'off'
                 and now-door.get('since', now) >= view['settings']['door_close_seconds']
                 and 'beneden' not in self.data['faults']
                 and ('cv' not in self.data['faults'] or cv_inactive))
        idle = True
        identities = [zone['temperature'], config['outdoor']]
        for source in ('beneden', 'cv'):
            entity = self.control.bindings[source]['entity_id']
            state = self.control.states.get(entity, {})
            attrs = state.get('attributes') or {}
            idle = idle and (state.get('state') == 'off' or
                             state.get('state') == 'heat' and attrs.get('hvac_action') == 'idle')
            identities.extend([entity, attrs.get('fan_mode'), attrs.get('preset_mode')])
        return dict(valid=bool(valid), indoor=indoor, outdoor=outdoor, idle=bool(idle),
                    identity=json.dumps(identities), weather=observed(config, self.control.states, now))

    def plan(self, config, now):
        settings = self.data['settings']
        view = self.schedule.view(now)
        sources = {s['id']: s for s in self.control.sources(now, config['stale_seconds'])}
        owned = self.data['owned']
        records = {c['id']: c for c in self.control.records()}
        holds = [h for h in view['overrides'] if h['active']]
        cv_idle = passive_idle(sources.get('cv', {}))
        manual_sources = {h['source'] for h in holds}
        blocked = {z for h in holds for z in h['zones']
                   if not (h['source'] == 'cv' and cv_idle)}
        # Existing manual heat/dry/cool and unconfirmed manual writes retain authority.
        for source, item in sources.items():
            if source == 'cv' and cv_idle:
                continue
            if source not in owned and (item['state'] not in ('off', None, 'unknown', 'unavailable') or item['pending']):
                blocked.update(COVERAGE[source])
        if view['legacy_pause']:
            blocked.update(('beneden', 'boven'))
        context = self.learning_context(config, view, now, blocked)
        learning = self.learning.recommendation(view, now, settings['enabled'] and self.armed, context)
        if view.get('temporary_temperature'):
            learning.update(phase='temporary', target=None, preheating=False)
        zones, demand = {}, {}
        floor_mode = False
        invalid_temperature = set()
        fresh = (self.control.connected and self.control.received is not None
                 and 0 <= now-self.control.received <= config['stale_seconds'])
        for zone in config['zones']:
            if zone.get('monitor_only'):
                continue
            zid = zone['id']
            req = view['comfort']['zones'][zid]
            goal = req['request']
            # A scheduled room floor below the airco's supported heat target is
            # guarded by room feedback, not forwarded as an invalid setpoint.
            if zid == 'beneden':
                minimum = sources[zid].get('heating_minimum')
                floor_mode = bool(view['settings']['enabled'] and view.get('current')
                                  and not view.get('temporary_temperature') and not learning['preheating']
                                  and goal and numeric(goal.get('target')) is not None
                                  and minimum is not None and goal['target'] < minimum)
                if floor_mode:
                    learning.update(phase='room_floor', target=None, preheating=False)
            if zid == 'beneden' and not floor_mode and learning['target'] is not None:
                target = learning['target']
                if learning['phase'] != 'coast':
                    target = max(target, (goal or {}).get('target') or 5)
                # A learned fractional target must not make the incumbent ineligible
                # and consequently send it off. Fall back to the schedule goal.
                incumbents = [s for s in ('beneden', 'cv') if s in owned and not owned[s].get('released')]
                def supports(source):
                    item = sources[source]
                    return (item['temperature_supported'] and item['minimum'] <= target <= item['maximum']
                            and math.isclose((target-item['minimum'])/item['step'],
                                             round((target-item['minimum'])/item['step']), abs_tol=.00001))
                supported = all(supports(s) for s in incumbents) if incumbents else any(supports(s) for s in ('beneden', 'cv'))
                if supported:
                    goal = dict(goal or {}, target=target)
                else:
                    learning.update(phase='unsupported_target', target=None, preheating=False)
            if zid == 'badkamer' and self.timer_active(now):
                goal = {'target': self.data['timer']['temperature']}
            sample = observation(zone['temperature'], self.control.states, now, True, '°C')
            temp = sample['value']
            reason = None
            try:
                age = now-timestamp(sample.get('source_reported') or sample.get('source_updated'))
            except (ValueError, TypeError, OverflowError):
                age = None
            if sample.get('report_error'):
                reason = 'Actuele ontvangsttijd temperatuur kon niet worden gecontroleerd.'
            elif not fresh or sample['quality'] != 'available' or age is None or not 0 <= age <= view['settings']['sensor_max_age_seconds']:
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
            if (sample.get('report_error') or not fresh or sample['quality'] != 'available'
                    or age is None or not 0 <= age <= view['settings']['sensor_max_age_seconds']):
                invalid_temperature.add(zid)
            target = goal['target'] if goal else None
            on = False
            maintaining = False
            if reason is None:
                on = temp < target if self.data['demand'].get(zid) else temp <= target-.3
                if zid == 'beneden' and floor_mode:
                    own = owned.get('beneden', {})
                    running = (own.get('floor_run') and not own.get('released')
                               and records.get(own.get('command'), {}).get('value') != 'off')
                    on = temp < target + .3 if running else temp <= target
                    if running and now-own.get('since', now) < 600:
                        on = True
                elif zid == 'beneden':
                    maintaining = any(source in owned and not owned[source].get('released')
                                      and records.get(owned[source]['command'], {}).get('value') != 'off'
                                      for source in ('beneden', 'cv'))
                    on = on or maintaining
            demand[zid] = on
            zones[zid] = dict(temperature=temp, target=target, demand=on, reason=reason or
                              ('Temperatuur handhaven.' if maintaining and temp >= target else
                               'Warmtevraag.' if on else 'Temperatuur bereikt; geen warmtevraag.'))
            if zid == 'beneden' and floor_mode and reason is None:
                zones[zid]['reason'] = ('Ondergrens bewaken; airco gebruikt minimaal 18 \u00b0C.' if on else
                    'Natuurlijk afkoelen; airco uit tot de kamerondergrens is bereikt.')
        rows, warnings = prices(self.control.states.get(config['price_entity']), config, now)
        price_interval = next((p for p in rows if p['start'] <= now < p['end']), None)
        price = price_interval['value'] if price_interval else None
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
        # A known open door reduces the fan of an existing airco run; it must
        # not cycle the compressor. New starts still require door_start.
        door_stop = door['value'] == 'unknown'
        down_owned = owned.get('beneden', {})
        down_command = records.get(down_owned.get('command'), {})
        door_pending = (door['value'] == 'on' and elapsed < view['settings']['door_open_seconds']
            and bool(down_owned) and not down_owned.get('released')
            and down_command.get('status') in PENDING and down_command.get('value') != 'off')
        door_continue = (not door_stop and bool(down_owned) and not down_owned.get('released')
            and sources['beneden']['state'] == 'heat'
            and down_command.get('status') in ('confirmed', 'already_set')
            and down_command.get('value') != 'off')

        def ineligible_reason(source, target):
            s = sources[source]
            if source in manual_sources or (source == 'cv' and cv_idle and source not in owned):
                return 'Handmatige bronkeuze of ruststand heeft voorrang.'
            if not s['available']:
                return s['reason'] or 'Geen actuele apparaatmelding.'
            if source in self.data['faults']:
                return self.data['faults'][source]
            if any(z in blocked for z in COVERAGE[source]):
                return 'Handmatige of gedeelde bron blokkeert deze ruimte.'
            if (source in ('beneden', 'boven') and 'cv' in owned and 'cv' in self.data['faults']
                    and not self.cv_handover_ready(sources, records)):
                return 'CV-opdracht mislukt; wachten op actuele bevestiging dat CV uit of veilig in rust staat.'
            if source == 'badkamer':
                return None
            if not s['temperature_supported'] or 'heat' not in s['modes'] or 'off' not in s['modes']:
                return 'Verwarmingsmodus of temperatuurgrenzen niet bevestigd.'
            if target is None:
                return 'Geen temperatuurdoel.'
            steps = (target-s['minimum'])/s['step']
            if not (s['minimum'] <= target <= s['maximum'] and math.isclose(steps, round(steps), abs_tol=.00001)):
                return 'Temperatuurdoel past niet bij apparaatgrenzen of stapgrootte.'
            return None

        def eligible(source, target):
            return ineligible_reason(source, target) is None

        desired = {}
        direct_desired = {}
        decision_basis = 'no_source'
        enabled = settings['enabled'] and self.armed
        if enabled and price is not None:
            for zid in ('beneden', 'boven', 'badkamer'):
                target = zones[zid]['target']
                if zid == 'beneden' and target is not None:
                    minimum = sources[zid].get('heating_minimum')
                    if minimum is not None:
                        target = max(target, minimum)
                if demand[zid] and eligible(zid, target):
                    if zid == 'beneden' and not (door_start or door_continue or door_pending):
                        zones[zid]['reason'] = 'Airco wacht op gesloten achterdeur en herstelvertraging.'
                    else:
                        desired[zid] = target
            direct_desired = dict(desired)
            if 'beneden' in desired:
                decision_basis = 'room_floor' if floor_mode else 'airco_preferred'
            down = zones['beneden']
            # The room thermostat is downstairs: it cannot independently heat upstairs.
            # The currently physically disabled CV is not a fallback for this
            # below-device-minimum floor policy. Comfort source choice is unchanged.
            cv_ok = (not floor_mode and demand['beneden'] and eligible('cv', down['target'])
                     and costs['cv'] is not None)
            if 'beneden' in desired and not floor_mode and not cv_ok:
                decision_basis = 'airco_available'
            if cv_ok and ('beneden' not in desired or costs['cv'] < costs['beneden']):
                decision_basis = 'cv_cheaper' if 'beneden' in desired else 'cv_fallback'
                desired.pop('beneden', None)
                desired.pop('boven', None)
                desired['cv'] = down['target']
            # Keep a viable incumbent for five minutes before an economic switch.
            for source, own in owned.items():
                c = records.get(own['command'], {})
                if floor_mode or own.get('released') or c.get('value') == 'off' or source in desired or now-own['since'] >= 300:
                    continue
                viable = (cv_ok if source == 'cv' else demand[source] and eligible(source, zones[source]['target'])
                          and (source != 'beneden' or door_start or door_continue or door_pending))
                if viable:
                    if source in ('cv', 'beneden'):
                        decision_basis = 'minimum_run'
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
        result = dict(desired=desired, zones=zones, demand=demand, costs=costs, price=price,
                    door_stop=door_stop, sources=sources, enabled=enabled,
                    estimate=True, strategy='current_heat_cost', preheating=learning['preheating'], learning=learning['enabled'], learning_status=learning, learning_context=context)
        result['cv_handover_seconds'] = max(60, 2 * config.get('poll_seconds', 30))
        result['room_floor_mode'] = floor_mode
        candidates = {}
        for source in ('beneden', 'cv'):
            target = zones['beneden']['target']
            if source == 'beneden' and target is not None and sources[source].get('heating_minimum') is not None:
                target = max(target, sources[source]['heating_minimum'])
            reason = ineligible_reason(source, target)
            if not reason and source == 'beneden' and not (door_start or door_continue or door_pending):
                reason = 'Airco wacht op gesloten achterdeur en herstelvertraging.'
            if not reason and source == 'cv' and floor_mode:
                reason = 'Kamerondergrens wordt door de airco bewaakt.'
            if not reason and source == 'cv' and costs['cv'] is None:
                reason = 'Geen geldig gastarief voor de kostenvergelijking.'
            candidates[source] = dict(eligible=reason is None, reason=reason)
        result['decision_inputs'] = dict(basis=decision_basis, candidates=candidates,
            prices=dict(electricity_eur_kwh=price, electricity_entity=config['price_entity'],
                interval=price_interval, confirmed=tariff_confirmed(config), warnings=warnings,
                gas_eur_m3=gas, gas_valid=bool(gas_valid and gas is not None and gas >= 0),
                gas_valid_until=config.get('gas_valid_until')))
        if hasattr(self, 'hourly_weather'):
            result['hourly_weather'] = self.hourly_weather(now)
        # A scheduled energy recipe must not replace an explicit room goal.
        if self.energy_start is not None and not view.get('temporary_temperature') and not floor_mode:
            result = self.energy_start.apply(result, config, now, direct_desired)
            if result.get('energy_start'):
                result['decision_inputs']['basis'] = 'energy_start'
        # A brief telemetry gap must not cycle an already confirmed airco. Keep
        # its existing device state only: no fresh start, target write or source
        # switch is authorized by this grace period. Persist the deadline so an
        # HC restart cannot repeatedly extend an unresolved gap.
        grace = []
        missing = self.data['missing_data_since']
        source = 'beneden'
        own = owned.get(source, {})
        command = records.get(own.get('command'), {})
        gap = (source in invalid_temperature or door['value'] == 'unknown'
               or price is None and tariff_confirmed(config))
        holding_allowed = (enabled and gap and source in owned and not own.get('released')
            and source not in blocked and source not in self.data['faults']
            and command.get('status') in ('confirmed', 'already_set')
            and command.get('value') != 'off'
            and sources[source]['state'] in ('heat', None, 'unknown', 'unavailable')
            and not view['comfort']['zones'][source]['errors']
            and zones[source]['target'] is not None
            and 5 <= zones[source]['target'] <= 35
            and not (door['value'] == 'on' and door_stop))
        if holding_allowed:
            since = missing.setdefault(source, now)
            if 0 <= now-since < 300:
                grace.append(source)
                zones[source]['reason'] = ('Meetgegevens tijdelijk niet beschikbaar; '
                    'bestaande aircostand blijft maximaal 5 minuten behouden.')
        else:
            missing.pop(source, None)
        result['data_grace_sources'] = grace
        return result

    def action(self, plan, now):
        records = {c['id']: c for c in self.control.records()}
        holds = {h['source'] for h in self.schedule.view(now)['overrides'] if h['active']}
        # Stop obsolete owned sources before any new start. Stop can preempt a start.
        for source, own in self.data['owned'].items():
            if not self.armed and source != 'badkamer':
                continue
            if source in holds or source in plan.get('data_grace_sources', []):
                continue
            c = records.get(own['command'], {})
            if (c.get('value') == 'off' or own.get('standby')) and not own.get('retry_stop'):
                continue  # Includes failed/uncertain stops: never replay automatically.
            if source not in plan['desired'] and plan['sources'][source]['available']:
                if source == 'cv':
                    if self.cv_handover_ready(plan['sources'], records):
                        continue
                    if plan['sources'][source]['pending']:
                        continue
                    if plan['sources'][source]['state'] != 'heat':
                        return source, 'mode', 'heat'
                    return source, 'heating', 15
                return source, 'state' if source == 'badkamer' else 'mode', 'off'
        desired = list(plan['desired'].items())
        if plan.get('energy_start'):
            desired.sort(key=lambda item: item[0] != plan['energy_start'].get('source', 'beneden'))
        for source, target in desired:
            if source in plan.get('data_grace_sources', []):
                continue
            s = plan['sources'][source]
            if s['pending'] or source in self.data['faults']:
                continue
            conflict = self.conflicting_sources(plan, source, records)
            if conflict:
                continue
            if (source not in self.data['owned'] or self.data['owned'][source].get('standby')) and now-self.data['changed'].get(source, -1e20) < 180:
                continue
            if source == 'badkamer':
                if s['state'] != 'on':
                    return source, 'state', 'on'
            elif s['state'] != 'heat' or not self.control.matches(s['temperature'], target):
                if source == 'cv' and s['state'] != 'heat':
                    return source, 'mode', 'heat'
                return source, 'heating', target
        return None

    def conflicting_sources(self, plan, source, records):
        return [other for other, own in self.data['owned'].items()
                if other != source and set(COVERAGE[source]) & set(COVERAGE[other])
                and not (other == 'cv' and self.cv_handover_ready(plan['sources'], records))]

    def cv_handover_ready(self, sources, records):
        """Release competing heat without erasing a failed CV command or replaying it."""
        own = self.data['owned'].get('cv', {})
        command = records.get(own.get('command'), {})
        cv = sources.get('cv', {})
        if not cv.get('available') or cv.get('pending'):
            return False
        if command.get('status') in FAILURES and cv.get('state') == 'off':
            return True
        return bool(own.get('standby')
                    and command.get('status') in ('confirmed', 'already_set')
                    and passive_idle(cv))

    def tick(self, config, now=None):
        now = time.time() if now is None else now
        if not self.armed and not (self.data['timer'] or {}).get('cleanup'):
            return
        self.reconcile(now)
        plan = self.plan(config, now)
        self.learning.observe(self.schedule.view(now), plan, now, max(180, 3*config.get('poll_seconds', 30)), plan['learning_context'])
        self.data['demand'] = plan['demand']
        from .decision import explain
        self.data['last_decision'] = explain(self, config, plan, now)
        self.save()  # Storage failure must precede all device writes.
        # One write per poll, prioritising stops; remaining independent sources follow.
        chosen = self.action(plan, now)
        if chosen is None:
            self.door_fan.tick(config, now)
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
            if source == 'cv' and source not in current['desired'] and field == 'heating':
                # Keep ownership to allow later CV demand, but do not count the
                # standby setpoint as a continuing comfort heat request.
                self.data['owned'][source].update(standby=True, released=True)
            if source == 'beneden' and field == 'heating' and current.get('room_floor_mode'):
                self.data['owned'][source]['floor_run'] = True
            if ((field == 'heating' or source == 'cv' and field == 'mode' and value == 'heat')
                    and source in current['desired'] and current.get('energy_start')
                    and source == current['energy_start'].get('source', 'beneden')):
                self.data['owned'][source]['energy_start'] = copy.deepcopy(current['energy_start'])
            self.data['changed'][source] = moment
            from .decision import explain
            self.data['last_command_decision'] = dict(explain(self, config, current, moment),
                command_id=request_id, command_source=source, command_field=field, command_value=value)
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
        from .decision import explain
        result['decision'] = explain(self, config, result, now)
        self.last_decision = copy.deepcopy(result['decision'])
        result['door_fan'] = self.door_fan.view(config, now, result)
        result.update(settings=copy.deepcopy(self.data['settings']), revision=self.data['revision'],
                      faults=copy.deepcopy(self.data['faults']), owned=copy.deepcopy(self.data['owned']))
        timer = copy.deepcopy(self.data['timer'])
        result['timer'] = dict(revision=self.data['timer_revision'], active=self.timer_active(now),
            remaining_seconds=max(0, timer['ends']-now) if self.timer_active(now) else 0,
            **(timer or dict(minutes=30, temperature=22, ends=None, status='idle')))
        return result
