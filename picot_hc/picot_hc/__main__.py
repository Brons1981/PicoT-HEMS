import argparse
import copy
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError

from .core import Store, fetch_states, snapshot, validate, number


class Runtime:
    def __init__(self, config, store, url, token):
        self.config, self.store, self.url, self.token = config, store, url, token
        self.settings_lock = threading.RLock()
        self.settings_revision = 0
        self.csrf_token = secrets.token_urlsafe(32)
        self.config = copy.deepcopy(config)
        saved_settings = store.settings()
        for zone in self.config['zones']:
            zone.update(saved_settings.get(zone['id'], {}))
        validate(self.config)
        self.connection = 'starting'
        self.error = None
        self.stop = threading.Event()

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
            self.settings_revision += 1
            return {'settings': zone, 'settings_revision': self.settings_revision}

    def collect(self):
        try:
            states = fetch_states(self.url, self.token)
            self.store.save(snapshot(self.config, states, time.time()), self.config['retention_days'])
            self.connection, self.error = 'connected', None
        except HTTPError as exc:
            self.connection, self.error = 'disconnected', 'HA antwoordt met HTTP ' + str(exc.code)
        except Exception as exc:
            # No URLs, tokens or remote exception bodies in logs or responses.
            self.connection, self.error = 'disconnected', 'Ophalen of opslaan mislukt (' + type(exc).__name__ + ')'

    def run(self):
        while not self.stop.is_set():
            self.collect()
            self.stop.wait(self.config['poll_seconds'])

    def current(self):
        data = self.store.latest()
        if data is None:
            data = snapshot(self.config, {}, time.time())
            data['collected'] = None
        age = time.time() - data['collected'] if data['collected'] is not None else None
        # Current settings must not wait for a new measurement or HA connectivity.
        with self.settings_lock:
            data['settings_revision'] = self.settings_revision
            zones = {z['id']: z for z in self.config['zones']}
            for zone in data['zones']:
                zone['settings'] = copy.deepcopy(zones.get(zone['id'], zone['settings']))
        data['csrf_token'] = self.csrf_token
        data.update(connection=self.connection, error=self.error, age_seconds=age,
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
            if urlsplit(self.path).path != '/api/settings':
                self.send_error(404)
                return
            if not secrets.compare_digest(self.headers.get('X-HC-CSRF', ''), runtime.csrf_token):
                self.send_error(403)
                return
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Ongeldig verzoekformaat.')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Ongeldige verzoekgrootte.')
                payload = json.loads(self.rfile.read(length))
                result = runtime.update_settings(payload)
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
        server.server_close()


if __name__ == '__main__':
    main()
