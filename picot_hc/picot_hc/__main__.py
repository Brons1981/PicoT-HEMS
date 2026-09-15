import argparse
import copy
import json
import os
import secrets
import sqlite3
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError

from .control import Control
from .schedule import Schedule, DOOR
from .building import building_observation
from .weather import DEFAULT_ENTITY, WeatherReader, forecast_view
from .core import Store, fetch_states, snapshot, validate, number, observation


class Runtime:
    def __init__(self, config, store, url, token):
        self.config, self.store, self.url, self.token = config, store, url, token
        self.settings_lock = threading.RLock()
        self.settings_revision = 0
        self.csrf_token = secrets.token_urlsafe(32)
        self.config = copy.deepcopy(config)
        # Confirmed entity list from Alex, 2026-09-15. Existing options may still be blank.
        for key, entity in {'outdoor': 'sensor.gw1200a_temperature_1',
                            'outdoor_dewpoint': 'sensor.gw1200a_dewpoint_1',
                            'outdoor_battery': 'binary_sensor.gw1200a_battery_1',
                            'outdoor_humidity': 'sensor.gw1200a_humidity_1'}.items():
            if not self.config.get(key):
                self.config[key] = entity
        sensor_defaults = {
            'beneden': {'dewpoint': 'sensor.gw1200a_indoor_dewpoint', 'battery': '', 'temperature': 'sensor.gw1200a_indoor_temperature', 'humidity': 'sensor.gw1200a_indoor_humidity'},
            'boven': {'dewpoint': 'sensor.gw1200a_dewpoint_2', 'battery': 'binary_sensor.gw1200a_battery_2', 'temperature': 'sensor.gw1200a_temperature_2', 'humidity': 'sensor.gw1200a_humidity_2'},
            'badkamer': {'dewpoint': 'sensor.gw1200a_dewpoint_3', 'battery': 'binary_sensor.gw1200a_battery_3', 'temperature': 'sensor.gw1200a_temperature_3', 'humidity': 'sensor.gw1200a_humidity_3'},
        }
        saved_settings = store.settings()
        for zone in self.config['zones']:
            for key, entity in sensor_defaults.get(zone['id'], {}).items():
                if not zone.get(key):
                    zone[key] = entity
            if (zone['id'] == 'badkamer'
                    and zone.get('device') == 'switch.1_5_3_badkamer_verwarming_badkamer'
                    and not zone.get('energy')):
                zone['energy'] = 'sensor.1_5_3_badkamer_verwarming_badkamer_energy'
            # Existing Supervisor options retain blank meter fields after updates.
            # Only supply defaults for Alex's confirmed upstairs air conditioner.
            if zone['id'] == 'boven' and zone.get('device') == 'climate.19791209313101_climate':
                for key, entity in {
                    'power': 'sensor.shellyplugsg3_d0cf13c907e0_vermogen',
                    'energy': 'sensor.shellyplugsg3_d0cf13c907e0_energie',
                }.items():
                    if not zone.get(key):
                        zone[key] = entity
            zone.update(saved_settings.get(zone['id'], {}))
        validate(self.config)
        self.control = Control(self.config, store, url, token)
        self.schedule = Schedule(self.control, store, self.config)
        previous = store.latest() or {}
        self.weather = WeatherReader(self.config.get('weather_entity', DEFAULT_ENTITY), previous.get('weather'))
        self.connection = 'starting'
        self.error = None
        self.stop = threading.Event()
        self.poll_now = threading.Event()

    def update_settings(self, payload):
        keys = {'minimum', 'target', 'maximum'}
        if not isinstance(payload, dict) or set(payload) != {'zone_id', 'values'}:
            raise ValueError('Ongeldig instellingenverzoek.')
        values = payload['values']
        if not isinstance(values, dict) or set(values) != keys:
            raise ValueError('Geef minimum, gewenste temperatuur en maximum op.')
        for v in values.values():
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)):
                raise ValueError('Gebruik een getal of laat het veld leeg.')
            if v is not None:
                number(v)
        with self.settings_lock:
            config = copy.deepcopy(self.config)
            zone = next((z for z in config['zones'] if z['id'] == payload['zone_id']), None)
            if zone is None:
                raise ValueError('Onbekende zone.')
            zone.update(values)
            try:
                validate(config)
            except ValueError:
                raise ValueError('Minimum moet kleiner dan of gelijk aan gewenst en maximum zijn.') from None
            self.store.save_settings(zone['id'], values)
            self.config = config
            self.schedule.config = config
            self.settings_revision += 1
            return {'settings': zone, 'settings_revision': self.settings_revision}

    def collect(self):
        with self.control.lock:
            self._collect()

    def _collect(self):
        try:
            started = time.time()
            states = fetch_states(self.url, self.token)
            now = time.time()
            self.control.observe(states, started, now)
            data = snapshot(self.config, states, now)
            data['building'] = building_observation(self.config, states, now, data, DOOR)
            data['weather'] = self.weather.collect(states, now, self.url, self.token)
            self.store.save(data, self.config['retention_days'])
            self.connection, self.error = 'connected', None
            self.schedule.tick(self.config)
        except HTTPError as exc:
            self.control.connected = False
            self.connection, self.error = 'disconnected', 'HA antwoordt met HTTP ' + str(exc.code)
        except Exception as exc:
            self.control.connected = False
            # No URLs, tokens or remote exception bodies in logs or responses.
            self.connection, self.error = 'disconnected', 'Ophalen of opslaan mislukt (' + type(exc).__name__ + ')'

    def run(self):
        while not self.stop.is_set():
            self.collect()
            self.poll_now.wait(self.config['poll_seconds'])
            self.poll_now.clear()

    def current(self):
        data = self.store.latest()
        if data is None:
            data = snapshot(self.config, {}, time.time())
            data['collected'] = None
        if 'outdoor_humidity' not in data:
            data['outdoor_humidity'] = observation(self.config.get('outdoor_humidity', ''), {}, time.time(), True, '%')
        age = time.time() - data['collected'] if data['collected'] is not None else None
        # Current settings must not wait for a new measurement or HA connectivity.
        with self.settings_lock:
            data['settings_revision'] = self.settings_revision
            zones = {z['id']: z for z in self.config['zones']}
            for zone in data['zones']:
                zone['settings'] = copy.deepcopy(zones.get(zone['id'], zone['settings']))
        if 'weather' not in data:
            from .weather import weather_now
            data['weather'] = weather_now(self.weather.entity, {}, time.time())
        weather = data['weather']
        weather['forecast'] = forecast_view(weather.get('forecast'), time.time(),
            'HA-verbinding niet actueel.' if self.connection != 'connected' or age is None or age > self.config['stale_seconds'] else None)
        data['sources'] = self.control.sources(time.time(), self.config['stale_seconds'])
        data['commands'] = self.control.records()[:20]
        with self.control.lock:
            data['schedule'] = self.schedule.view(time.time())
        data['control_mode'] = 'comfort_input'
        data['csrf_token'] = self.csrf_token
        data.update(connection=self.connection, error=self.error, age_seconds=age,
                    retention_days=self.config['retention_days'],
                    stale=age is None or age > self.config['stale_seconds'])
        return data


def handler(runtime, ingress):
    web = Path(__file__).parent / 'web'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if ingress and self.client_address[0] != '172.30.32.2':
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path not in ('/api/settings', '/api/commands', '/api/schedule', '/api/resume'):
                self.send_error(404)
                return
            if not secrets.compare_digest(self.headers.get('X-HC-CSRF', ''), runtime.csrf_token):
                self.send_error(403)
                return
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Ongeldig verzoekformaat.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= (32768 if path == '/api/schedule' else 4096):
                    raise ValueError('Ongeldige verzoekgrootte.')
                payload = json.loads(self.rfile.read(length))
                with runtime.control.lock:
                    if path == '/api/settings':
                        result = runtime.update_settings(payload)
                    elif path == '/api/commands':
                        result = {'command': runtime.control.submit(payload, runtime.config['stale_seconds'])}
                    elif path == '/api/schedule':
                        result = {'schedule': runtime.schedule.update(payload, time.time())}
                    else:
                        if payload != {}:
                            raise ValueError('Ongeldig hervatverzoek.')
                        started = time.time()
                        try:
                            states = fetch_states(runtime.url, runtime.token)
                        except Exception:
                            raise ValueError('HA niet bereikbaar; HC blijft gepauzeerd.') from None
                        runtime.control.observe(states, started, time.time())
                        result = {'schedule': runtime.schedule.resume(time.time())}
                runtime.poll_now.set()
                self.send_json(200, result)
            except (ValueError, TypeError, UnicodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            except sqlite3.Error:
                self.send_json(503, {'error': 'Opslaan mislukt. Probeer opnieuw.'})

        def send_json(self, status, data):
            body = json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if ingress and self.client_address[0] != '172.30.32.2':
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == '/api/building-export':
                self.export_building()
                return
            if path == '/api/snapshot':
                body = json.dumps(runtime.current(), allow_nan=False).encode()
                mime = 'application/json'
            elif path == '/api/history':
                body = json.dumps(runtime.store.history(time.time() - 86400), allow_nan=False).encode()
                mime = 'application/json'
            elif path in ('/', '/index.html', '/app.js', '/style.css'):
                name = 'index.html' if path == '/' else path[1:]
                body = (web / name).read_bytes()
                mime = {'html':'text/html', 'js':'text/javascript', 'css':'text/css'}[name.split('.')[-1]]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'self'")
            self.end_headers()
            self.wfile.write(body)

        def export_building(self):
            until = time.time()
            self.send_response(200)
            self.send_header('Content-Type', 'application/gzip')
            self.send_header('Content-Disposition', 'attachment; filename="picot-hc-woningmetingen.jsonl.gz"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            compressor = zlib.compressobj(wbits=31)
            metadata = dict(format='picot_hc_building_history', version=1, exported_until=until,
                            retention_days=runtime.config['retention_days'])
            try:
                self.wfile.write(compressor.compress((json.dumps(metadata) + '\n').encode()))
                for record in runtime.store.building_records(until):
                    self.wfile.write(compressor.compress((json.dumps(record, allow_nan=False) + '\n').encode()))
                self.wfile.write(compressor.flush())
            except (BrokenPipeError, ConnectionResetError):
                pass  # A cancelled download must not affect the collector.
    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='/data/options.json')
    p.add_argument('--data', default='/data')
    p.add_argument('--port', type=int, default=8099)
    args = p.parse_args()
    config = json.loads(Path(args.config).read_text())
    validate(config)
    directory = Path(args.data)
    directory.mkdir(parents=True, exist_ok=True)
    supervisor = os.environ.get('SUPERVISOR_TOKEN', '')
    rt = Runtime(config, Store(directory / 'hc.sqlite3'),
                 'http://supervisor/core/api' if supervisor else os.environ.get('HC_HA_API', 'http://127.0.0.1:8123/api'),
                 supervisor or os.environ.get('HC_HA_TOKEN', ''))
    threading.Thread(target=rt.run, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0' if supervisor else '127.0.0.1', args.port), handler(rt, bool(supervisor)))
    try:
        server.serve_forever()
    finally:
        rt.stop.set()
        rt.poll_now.set()
        server.server_close()


if __name__ == '__main__':
    main()
