"""Explicit manual device commands, durable intent and independent HA feedback."""
import copy
import json
import math
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from .core import NoRedirect, fetch_states, number

PENDING = {'sending', 'awaiting_feedback', 'uncertain'}
MODES = {'off', 'heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only'}
# Confirmed by the owner; only used when this entity omits HA step metadata.
CONFIRMED_CELSIUS_STEPS = {'climate.huiskamer': 0.5}


def source_bindings(config):
    result = {'cv': {'name': 'Cv · beneden en boven', 'entity_id': config['cv'], 'kind': 'climate'}}
    for zone in config['zones']:
        if zone['id'] in ('beneden', 'boven', 'badkamer'):
            result[zone['id']] = {'name': zone['name'], 'entity_id': zone['device'],
                                 'kind': 'switch' if zone['id'] == 'badkamer' else 'climate'}
    return result


def ha_request(url, token, path, payload=None):
    if not token:
        raise ValueError('HA-verbinding ontbreekt.')
    req = Request(url.rstrip('/') + path, headers={'Authorization': 'Bearer ' + token,
                  'Content-Type': 'application/json'},
                  data=None if payload is None else json.dumps(payload, allow_nan=False).encode())
    with build_opener(NoRedirect).open(req, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else None


def numeric(value):
    try:
        return number(value) if value is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


class Control:
    def __init__(self, config, store, url, token):
        self.store, self.url, self.token = store, url, token
        self.bindings = source_bindings(config)
        self.timeout = config.get('command_timeout_seconds', 300)
        if not isinstance(self.timeout, int) or not 30 <= self.timeout <= 900:
            raise ValueError('command_timeout_seconds moet tussen 30 en 900 liggen.')
        self.lock = threading.RLock()
        self.states, self.received, self.unit = {}, None, None
        self.connected = False
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL)')
        for command in self.records():
            if command['status'] in PENDING:
                command.update(status='interrupted', error='HC herstart; controleer de gemelde apparaatstand.', finished=time.time())
                self.save(command)

    def records(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM commands ORDER BY created DESC')]

    def save(self, command):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO commands VALUES (?, ?, ?)',
                       (command['id'], command['created'], json.dumps(command, allow_nan=False)))

    def record_intent(self, command, superseded):
        # Preemption and the new intent must either both persist or neither.
        with self.store.connect() as db:
            for record in [*superseded, command]:
                db.execute('INSERT OR REPLACE INTO commands VALUES (?, ?, ?)',
                           (record['id'], record['created'], json.dumps(record, allow_nan=False)))

    def expire(self, now):
        for command in self.records():
            if command['status'] in PENDING and now >= command['deadline']:
                command.update(status='timed_out', finished=now, error='Geen bevestiging binnen de wachttijd. Controleer het apparaat.')
                self.save(command)

    def observe(self, states, started, received):
        with self.lock:
            self.states, self.received, self.connected = copy.deepcopy(states), received, True
            if self.unit is None and any(states.get(b['entity_id'], {}).get('state') not in (None, 'unknown', 'unavailable') for b in self.bindings.values() if b['kind'] == 'climate'):
                try:
                    self.unit = ha_request(self.url, self.token, '/config')['unit_system']['temperature']
                except Exception:
                    self.unit = None
            self.expire(received)
            for command in self.records():
                if command['status'] not in PENDING or started <= command['sent']:
                    continue
                item = states.get(command['entity_id'], {})
                if item.get('state') in (None, 'unknown', 'unavailable'):
                    continue
                actual = item.get('attributes', {}).get('temperature') if command['field'] == 'temperature' else item['state']
                command['reported'] = {'value': actual, 'received': received, 'source_updated': item.get('last_updated')}
                if self.matches(actual, command['value']):
                    command.update(status='confirmed', finished=received, error=None)
                self.save(command)

    @staticmethod
    def matches(actual, desired):
        if isinstance(desired, (int, float)):
            val = numeric(actual)
            return val is not None and math.isclose(val, desired, abs_tol=0.001)
        return actual == desired

    def sources(self, now, stale_seconds):
        with self.lock:
            self.expire(now)
            records = self.records()
            result = []
            for source_id, binding in self.bindings.items():
                entity = binding['entity_id']
                item = self.states.get(entity, {})
                attrs = item.get('attributes') or {}
                fresh = self.connected and self.received is not None and now - self.received <= stale_seconds
                available = fresh and item.get('state') not in (None, 'unknown', 'unavailable') and entity.startswith(binding['kind'] + '.')
                modes = attrs.get('hvac_modes', [])
                modes = [m for m in modes if m in MODES] if isinstance(modes, list) else []
                minimum, maximum, step = [numeric(attrs.get(k)) for k in ('min_temp', 'max_temp', 'target_temp_step')]
                if attrs.get('target_temp_step') is None and self.unit == '°C':
                    step = CONFIRMED_CELSIUS_STEPS.get(entity)
                features = attrs.get('supported_features', 0)
                temperature_ok = (isinstance(features, int) and bool(features & 1) and self.unit == '°C'
                                  and minimum is not None and maximum is not None and minimum <= maximum
                                  and step is not None and step > 0)
                pending = next((c for c in records if c['entity_id'] == entity and c['status'] in PENDING), None)
                result.append(dict(binding, id=source_id, available=available, pending=bool(pending),
                    modes=modes, minimum=minimum, maximum=maximum, step=step, unit=self.unit,
                    temperature_supported=temperature_ok, state=item.get('state'),
                    temperature=numeric(attrs.get('temperature')), action=attrs.get('hvac_action'),
                    received=self.received, source_updated=item.get('last_updated'),
                    reason=None if available else 'Geen actuele, bruikbare HA-terugmelding.'))
            return result

    def submit(self, payload, stale_seconds):
        if not isinstance(payload, dict) or set(payload) != {'request_id', 'source', 'field', 'value'}:
            raise ValueError('Ongeldige bronopdracht.')
        request_id = payload['request_id']
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_id):
            raise ValueError('Ongeldig opdracht-ID.')
        if not isinstance(payload['source'], str) or payload['source'] not in self.bindings:
            raise ValueError('Onbekende bron.')
        with self.lock:
            records = self.records()
            existing = next((c for c in records if c['id'] == request_id), None)
            if existing:
                if any(existing[k] != payload[k] for k in ('source', 'field', 'value')):
                    raise ValueError('Dit opdracht-ID hoort bij een andere opdracht.')
                return existing
            # Fresh independent read immediately before any device write.
            started = time.time()
            try:
                states = fetch_states(self.url, self.token)
            except Exception:
                self.connected = False
                raise ValueError('HA niet bereikbaar; geen opdracht verstuurd.') from None
            self.observe(states, started, time.time())
            binding = self.bindings[payload['source']]
            if payload['field'] == 'temperature':
                try:
                    self.unit = ha_request(self.url, self.token, '/config')['unit_system']['temperature']
                except Exception:
                    self.unit = None
            source = next(s for s in self.sources(time.time(), stale_seconds) if s['id'] == payload['source'])
            if not source['available']:
                raise ValueError(source['reason'])
            field, value = payload['field'], payload['value']
            data = {'entity_id': binding['entity_id']}
            if field == 'state' and binding['kind'] == 'switch' and value in ('on', 'off'):
                service = '/services/switch/turn_' + value
            elif field == 'mode' and binding['kind'] == 'climate' and isinstance(value, str) and value in source['modes']:
                service = '/services/climate/set_hvac_mode'
                data['hvac_mode'] = value
            elif field == 'temperature' and binding['kind'] == 'climate':
                if not source['temperature_supported'] or isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError('Temperatuurgrenzen, stap of °C-eenheid niet bevestigd door HA.')
                value = number(value)
                steps = (value - source['minimum']) / source['step']
                if not source['minimum'] <= value <= source['maximum'] or not math.isclose(steps, round(steps), abs_tol=0.00001):
                    raise ValueError('Temperatuur ligt buiten apparaatgrenzen of past niet bij de stapgrootte.')
                if source['state'] not in ('heat', 'cool', 'auto'):
                    raise ValueError('Kies eerst een geschikte apparaatmodus voor een temperatuurdoel.')
                service = '/services/climate/set_temperature'
                data['temperature'] = value
            else:
                raise ValueError('Opdracht of modus wordt niet ondersteund.')
            pending = [c for c in self.records() if c['entity_id'] == binding['entity_id'] and c['status'] in PENDING]
            if pending and value != 'off':
                raise ValueError('Er loopt nog een opdracht. Wacht op terugmelding of kies Uit.')
            now = time.time()
            for old in pending:
                old.update(status='superseded', finished=now, error='Vervangen door expliciete uit-opdracht.')
            actual = source['temperature'] if field == 'temperature' else source['state']
            command = dict(id=request_id, source=payload['source'], entity_id=binding['entity_id'],
                           field=field, value=value, created=now, sent=None, accepted=None,
                           deadline=now+self.timeout, finished=None, status='sending', error=None,
                           reported={'value':actual, 'received':self.received, 'source_updated':source['source_updated']})
            if self.matches(actual, value) and not pending:
                command.update(status='already_set', finished=now)
                self.save(command)
                return command
            command['sent'] = now
            self.record_intent(command, pending)  # A failing transaction prevents dispatch.
            try:
                ha_request(self.url, self.token, service, data)
                command.update(status='awaiting_feedback', accepted=time.time())
            except HTTPError as exc:
                command.update(status='failed' if 400 <= exc.code < 500 and exc.code != 408 else 'uncertain',
                               error='HA antwoordt met HTTP ' + str(exc.code))
            except Exception as exc:
                command.update(status='uncertain', error='Verzendresultaat onbekend ('+type(exc).__name__+'); geen automatische herhaling.')
            if command['status'] == 'failed':
                command['finished'] = time.time()
            self.save(command)
            return command
