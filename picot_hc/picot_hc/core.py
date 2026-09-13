import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return parsed.timestamp()


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measurement')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Measurement is not finite')
    return result


def validate(config):
    if not 10 <= config['poll_seconds'] <= 300:
        raise ValueError('poll_seconds must be between 10 and 300')
    if not 1 <= config['retention_days'] <= 365:
        raise ValueError('retention_days must be between 1 and 365')
    if config['stale_seconds'] < 2 * config['poll_seconds']:
        raise ValueError('stale_seconds must be at least twice poll_seconds')
    for z in config['zones']:
        vals = [z.get(k) for k in ('minimum', 'target', 'maximum')]
        vals = [number(v) for v in vals if v is not None]
        if vals != sorted(vals):
            raise ValueError('Temperature bounds must be ordered')
        low, target, high = [number(z[k]) for k in ('humidity_min', 'humidity_target', 'humidity_max')]
        if not 0 <= low <= target <= high <= 100:
            raise ValueError('Humidity bounds must be ordered within 0..100')
    if len({z['id'] for z in config['zones']}) != len(config['zones']):
        raise ValueError('Zone identifiers must be unique')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the HA credential to another endpoint.


def fetch_states(base_url, token):
    if not token:
        raise ValueError('HA token missing')
    req = Request(base_url.rstrip('/') + '/states', headers={'Authorization': 'Bearer ' + token})
    with build_opener(NoRedirect).open(req, timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, list) or any(not isinstance(x, dict) or 'entity_id' not in x for x in payload):
        raise ValueError('Invalid HA state response')
    return {x['entity_id']: x for x in payload}


def observation(entity, states, now, numeric=False, unit=None):
    result = dict(entity_id=entity, value=None, quality='not_configured', received=now, source_updated=None, unit=unit)
    if not entity:
        return result
    result['quality'] = 'missing'
    item = states.get(entity)
    if item is None:
        return result
    result['source_updated'] = item.get('last_updated')
    state = item.get('state')
    attrs = item.get('attributes') or {}
    if state in (None, 'unknown', 'unavailable'):
        result['quality'] = state if state in ('unknown', 'unavailable') else 'invalid'
        return result
    if numeric:
        try:
            state = number(state)
        except (ValueError, TypeError):
            result['quality'] = 'invalid'
            return result
        if unit and attrs.get('unit_of_measurement') != unit:
            result['quality'] = 'unit_mismatch'
            return result
    result.update(value=state, quality='available')
    return result


# Alex confirmed this configured tariff source on 2026-09-13.
CONFIRMED_PRICE_ENTITY = 'sensor.nordpool_kwh_nl_eur_3_095_0'


def tariff_confirmed(config):
    return bool(config.get('price_basis_confirmed', False) or
                config['price_entity'] == config.get('confirmed_price_entity', CONFIRMED_PRICE_ENTITY))


def prices(item, config, now):
    """Explicit interval data only: never infer intervals from array length."""
    if not item or item.get('state') in ('unknown', 'unavailable'):
        return [], ['Prijsbron ontbreekt of is niet beschikbaar.']
    attrs = item.get('attributes') or {}
    unit = attrs.get('unit_of_measurement')
    factors = {'EUR/kWh': 1, '€/kWh': 1, 'EUR/MWh': .001, '€/MWh': .001}
    if unit not in factors:
        return [], ['Prijseenheid niet ondersteund of onbekend: ' + str(unit)]
    rows, errors = {}, []
    for key in config['price_attributes']:
        raw_rows = attrs.get(key, []) or []
        if not isinstance(raw_rows, list):
            errors.append('Prijsattribuut moet een lijst met tijdvakken bevatten.')
            continue
        for raw in raw_rows:
            try:
                start, end = timestamp(raw['start']), timestamp(raw['end'])
                value = number(raw['value']) * factors[unit]
                if end <= start:
                    raise ValueError('Invalid interval')
                if start < now + 172800 and end > now - 86400:
                    record = dict(start=start, end=end, value=value)
                    if start in rows and rows[start] != record:
                        raise ValueError('Conflicting interval')
                    rows[start] = record
            except (TypeError, KeyError, ValueError):
                errors.append('Ongeldig of conflicterend prijsinterval; controleer bronattributen.')
    ordered = sorted(rows.values(), key=lambda x: x['start'])
    if any(a['end'] > b['start'] for a, b in zip(ordered, ordered[1:])):
        errors.append('Overlappende prijsintervallen.')
    if errors:
        return [], sorted(set(errors))
    if not ordered:
        errors.append('Geen prijzen met expliciete start- en eindtijd ontvangen.')
    elif not any(p['start'] <= now < p['end'] for p in ordered):
        errors.append('Prijs voor het huidige tijdvak ontbreekt.')
    if not tariff_confirmed(config):
        errors.append('Tariefbasis nog niet bevestigd; bedragen worden alleen als bronprijzen getoond.')
    return ordered, errors


def snapshot(config, states, now):
    zones = []
    for z in config['zones']:
        samples = {}
        for key, unit in [('temperature', '°C'), ('humidity', '%'), ('power', 'W'), ('energy', 'kWh')]:
            samples[key] = observation(z.get(key, ''), states, now, True, unit)
        samples['device'] = observation(z['device'], states, now)
        reason = 'Observatie: geen automatische aansturing.'
        if samples['temperature']['quality'] != 'available':
            reason = 'Temperatuurmeting ontbreekt of is niet bruikbaar.'
        zones.append(dict(id=z['id'], name=z['name'], samples=samples, settings=z, reason=reason))
    points, warnings = prices(states.get(config['price_entity']), config, now)
    return dict(mode='observe', collected=now, connection='connected', zones=zones,
                outdoor=observation(config['outdoor'], states, now, True, '°C'),
                presence=observation(config['presence'], states, now),
                cv=observation(config['cv'], states, now),
                cv_status=observation(config['cv_status'], states, now),
                gas=observation(config['gas'], states, now, True, 'm³'),
                co2=observation(config['co2'], states, now, True, 'ppm'),
                gas_price=config['gas_price'], gas_valid_until=config['gas_valid_until'],
                prices=points, warnings=warnings, price_basis_confirmed=tariff_confirmed(config))


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS samples (time REAL PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS zone_settings (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, data, retention_days):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO samples VALUES (?, ?)',
                       (data['collected'], json.dumps(data, allow_nan=False)))
            db.execute('DELETE FROM samples WHERE time < ?', (data['collected'] - retention_days * 86400,))

    def latest(self):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM samples ORDER BY time DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def history(self, since):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM samples WHERE time >= ? ORDER BY time', (since,)).fetchall()
        # Small response: graph inputs only, no full HA state inventory.
        return [dict(time=d['collected'], zones=[dict(id=z['id'], samples={k:z['samples'][k] for k in ('temperature','humidity','power')}) for z in d['zones']]) for d in map(lambda r:json.loads(r[0]), rows)]

    def settings(self):
        with self.connect() as db:
            return {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM zone_settings')}

    def save_settings(self, zone_id, values):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO zone_settings VALUES (?, ?)',
                       (zone_id, json.dumps(values, allow_nan=False)))
