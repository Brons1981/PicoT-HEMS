"""Weather observations and daily forecasts; no climate control authority."""
import copy
import json
import time
from datetime import datetime
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from .core import NoRedirect, number, observation, timestamp

DEFAULT_ENTITY = 'weather.buienradar'


def optional_number(value):
    try:
        return number(value) if value is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def weather_now(entity, states, now):
    condition = observation(entity, states, now)
    item = states.get(entity) or {}
    attrs = item.get('attributes') or {}
    metrics = {}
    for key, unit_key, allowed in [
        ('temperature', 'temperature_unit', ('°C', '°F')),
        ('apparent_temperature', 'temperature_unit', ('°C', '°F')),
        ('wind_gust_speed', 'wind_speed_unit', ('km/h', 'm/s', 'mph', 'kn')),
        ('humidity', None, ('%',)),
        ('wind_speed', 'wind_speed_unit', ('km/h', 'm/s', 'mph', 'kn')),
        ('pressure', 'pressure_unit', ('hPa', 'Pa', 'inHg', 'mmHg')),
    ]:
        unit = attrs.get(unit_key) if unit_key else '%'
        value = optional_number(attrs.get(key)) if condition['quality'] == 'available' else None
        quality = 'available' if value is not None and unit in allowed else 'unavailable'
        metrics[key] = {'value': value if quality == 'available' else None,
                        'unit': unit, 'quality': quality}
    return {'entity_id': entity, 'condition': condition, 'metrics': metrics}


def fetch_forecast(base_url, token, entity):
    if not token:
        raise ValueError('HA token missing')
    # Fixed read-only HA action, never a caller-selected service or device command.
    req = Request(base_url.rstrip('/') + '/services/weather/get_forecasts?return_response',
                  data=json.dumps({'entity_id': entity, 'type': 'daily'}).encode(),
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with build_opener(NoRedirect).open(req, timeout=10) as response:
        payload = json.load(response)
    rows = payload['service_response'][entity]['forecast']
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Invalid forecast response')
    result = []
    for row in rows:
        point = {'time': timestamp(row['datetime']),
                 'condition': row.get('condition') if isinstance(row.get('condition'), str) else None}
        for key in ('temperature', 'templow', 'precipitation', 'precipitation_probability', 'wind_speed'):
            point[key] = optional_number(row.get(key))
        result.append(point)
    if len({r['time'] for r in result}) != len(result):
        raise ValueError('Duplicate forecast timestamp')
    return sorted(result, key=lambda r: r['time'])


class WeatherReader:
    def __init__(self, entity, previous=None):
        self.entity = entity
        self.next_attempt = 0
        self.cache = None
        if previous and previous.get('entity_id') == entity:
            self.cache = copy.deepcopy(previous.get('forecast'))

    def collect(self, states, now, url, token):
        data = weather_now(self.entity, states, now)
        if not self.entity:
            data['forecast'] = None
            return data
        if data['condition']['quality'] != 'available':
            data['forecast'] = self.view(now, 'Weerbron niet beschikbaar.')
            return data
        if time.monotonic() >= self.next_attempt:
            self.next_attempt = time.monotonic() + 300
            try:
                rows = fetch_forecast(url, token, self.entity)
                attrs = states[self.entity].get('attributes') or {}
                self.cache = {'type': 'daily', 'received': now, 'rows': rows, 'error': None,
                              'temperature_unit': attrs.get('temperature_unit'),
                              'precipitation_unit': attrs.get('precipitation_unit'),
                              'wind_speed_unit': attrs.get('wind_speed_unit')}
                self.next_attempt = time.monotonic() + 1800
            except Exception as exc:
                if self.cache is None:
                    self.cache = {'type': 'daily', 'received': None, 'rows': []}
                self.cache['error'] = 'Verwachting ophalen mislukt (' + type(exc).__name__ + ').'
        data['forecast'] = self.view(now)
        return data

    def view(self, now, error=None):
        return forecast_view(self.cache, now, error)


def forecast_view(cache, now, error=None):
    data = copy.deepcopy(cache) if cache else {'type': 'daily', 'received': None, 'rows': []}
    if error:
        data['error'] = error
    received = data.get('received')
    data['stale'] = received is None or now - received > 7200 or bool(data.get('error'))
    today = datetime.fromtimestamp(now, ZoneInfo('Europe/Amsterdam')).date()
    data['rows'] = [r for r in data.get('rows', [])
                    if 0 <= (datetime.fromtimestamp(r['time'], ZoneInfo('Europe/Amsterdam')).date() - today).days < 7]
    return data
