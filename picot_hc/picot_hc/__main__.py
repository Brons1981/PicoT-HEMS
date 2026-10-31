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
from .heating import Heating
from .energy_outlook import read_outlook
from .energy_portfolio import read_assessment
from .energy_measurement import measurement, MeasurementPublisher
from .energy_model import context as energy_context
from .energy_model import meter_context
from .energy_proposals import Proposals, ProposalPublisher
from .warmup_energy import WarmupEnergy
from .startup_energy import StartupEnergy
from .cv_gas_screening import gas_screening
from .cv_auxiliary_history import AuxiliaryHistory
from .cv_auxiliary import assumptions as cv_assumptions
from .cv_warmup import CvWarmupEvidence, cv_sample
from .cv_maintenance import CvMaintenance
from .delayed_start import idle_context
from .energy_selection import Selection, ENTITY as SELECTION_ENTITY
from .start_intent import StartIntent
from .energy_start import EnergyStart
from .energy_execution import (execution_receipt, ENTITY as EXECUTION_ENTITY,
                               reservation_receipt, RESERVATION_ENTITY)
from .building import building_observation
from .weather import DEFAULT_ENTITY, WeatherReader, forecast_view
from .core import Store, fetch_states, snapshot, validate, number, observation
from .health_notifications import HealthNotifier
from .tablet import EnergyReader, authorized, tablet_view


class Runtime:
    def __init__(self, config, store, url, token):
        self.config, self.store, self.url, self.token = config, store, url, token
        self.settings_lock = threading.RLock()
        self.settings_revision = 0
        self.csrf_token = secrets.token_urlsafe(32)
        self.config = copy.deepcopy(config)
        # Move the former outdoor channel to passive garage monitoring.
        outdoor_defaults = {'outdoor':'sensor.0_energie_gw1200a_outdoor_temperature','outdoor_humidity':'sensor.0_energie_gw1200a_humidity','outdoor_dewpoint':'sensor.0_energie_gw1200a_dewpoint','outdoor_vpd':'sensor.0_energie_gw1200a_vapour_pressure_deficit','outdoor_battery':'binary_sensor.0_energie_gw1200a_wh26_battery'}
        old_outdoor = {'outdoor': 'sensor.gw1200a_temperature_1',
                       'outdoor_humidity': 'sensor.gw1200a_humidity_1',
                       'outdoor_dewpoint': 'sensor.gw1200a_dewpoint_1',
                       'outdoor_battery': 'binary_sensor.gw1200a_battery_1'}
        for key, entity in outdoor_defaults.items():
            if not self.config.get(key) or self.config.get(key) == old_outdoor.get(key):
                self.config[key] = entity
        if not any(z['id'] == 'garage' for z in self.config['zones']):
            self.config['zones'].append({'id':'garage','name':'Garage','device':'','temperature':'sensor.gw1200a_temperature_1','humidity':'sensor.gw1200a_humidity_1','dewpoint':'sensor.gw1200a_dewpoint_1','battery':'binary_sensor.gw1200a_battery_1','power':'','energy':'','monitor_only':True,'humidity_min':40,'humidity_target':50,'humidity_max':60})
        for zone in self.config['zones']:
            if zone['id'] == 'garage':
                zone['monitor_only'] = True
                zone['device'] = ''
        sensor_defaults = {
            'garage': {'temperature': 'sensor.gw1200a_temperature_1', 'humidity': 'sensor.gw1200a_humidity_1', 'dewpoint': 'sensor.gw1200a_dewpoint_1', 'battery': 'binary_sensor.gw1200a_battery_1'},
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
        self.notifications = HealthNotifier(
            token, 'HC', Path(store.path).with_name('hc_health_notifications.json'),
            enabled=self.config.get('health_notifications_enabled', True),
            recovery_enabled=self.config.get('health_notifications_recovery_enabled', True))
        self.control = Control(self.config, store, url, token, notifications=self.notifications)
        self.schedule = Schedule(self.control, store, self.config)
        self.heating = Heating(self.control, self.schedule, store)
        self.energy_publisher = MeasurementPublisher(url, token)
        self.auxiliary_history = AuxiliaryHistory()
        self.energy_proposals = Proposals(store, ProposalPublisher(url, token))
        self.start_intent = StartIntent(store)
        self.energy_selection = Selection(store, ProposalPublisher(url, token, SELECTION_ENTITY))
        self.energy_execution_publisher = ProposalPublisher(url, token, EXECUTION_ENTITY)
        self.energy_reservation_publisher = ProposalPublisher(url, token, RESERVATION_ENTITY)
        self.warmup_energy = WarmupEnergy(store)
        self.warmup_sample = None
        self.startup_energy = StartupEnergy(store)
        self.cv_warmup = CvWarmupEvidence(store)
        self.cv_maintenance = CvMaintenance(store)
        self.heating.energy_start = EnergyStart(self.heating, self.start_intent,
                                               self.startup_energy, self.energy_proposals.model)
        self.heating.energy_start.cv_warmup = self.cv_warmup
        self.heating.energy_start.cv_maintenance = self.cv_maintenance
        self.startup_sample = None
        previous = store.latest() or {}
        self.weather = WeatherReader(self.config.get('weather_entity', DEFAULT_ENTITY), previous.get('weather'))
        self.heating.hourly_weather = self.weather.hourly.view
        self.energy_proposals.cooling = self.heating.learning.cooling
        self.connection = 'starting'
        self.error = None
        self.stop = threading.Event()
        self.poll_now = threading.Event()
        self.tablet_energy = EnergyReader(self)

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
            if zone.get('monitor_only'):
                raise ValueError('Deze ruimte wordt alleen gemonitord.')
            if zone['id'] == 'beneden':
                raise ValueError('Stel beneden in via het comfortschema of de handmatige thermostaat.')
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
            states = fetch_states(self.url, self.token, self.control.report_entities)
            now = time.time()
            self.control.observe(states, started, now)
            data = snapshot(self.config, states, now)
            data['building'] = building_observation(self.config, states, now, data, DOOR)
            data['energy_measurement'] = measurement(self.config, states, now)
            data['energy_measurement']['estimated_component'] = self.auxiliary_history.sample(
                self.config, states, now)
            data['weather'] = self.weather.collect(states, now, self.url, self.token)
            self.store.save(data, self.config['retention_days'])
            self.connection, self.error = 'connected', None
            self.schedule.tick(self.config)
            self._prepare_startup()
            self._cv_evidence(prepare=True)
            self.heating.tick(self.config)
            self.energy_publisher.submit(data['energy_measurement'])
        except HTTPError as exc:
            self.control.connected = False
            self.connection, self.error = 'disconnected', 'HA antwoordt met HTTP ' + str(exc.code)
        except Exception as exc:
            self.control.connected = False
            # No URLs, tokens or remote exception bodies in logs or responses.
            self.connection, self.error = 'disconnected', 'Ophalen of opslaan mislukt (' + type(exc).__name__ + ')'
        self._energy_advice()
        self._cv_evidence()
        try:
            self.energy_execution_publisher.submit(execution_receipt(
                self.start_intent, self.control, self.config, time.time()))
        except Exception:
            self.energy_execution_publisher.submit(dict(state='unavailable', attributes={}))
        try:
            self.energy_reservation_publisher.submit(reservation_receipt(
                self.start_intent, self.control, self.heating, self.config, time.time()))
        except Exception:
            self.energy_reservation_publisher.submit(dict(state='unavailable', attributes={}))
        self._notify_health()

    def _cv_evidence(self, prepare=False):
        # Passive collection must not interrupt heating or authorize a new source.
        try:
            now = time.time()
            plan, view = self.heating.view(self.config, now), self.schedule.view(now)
            if not prepare:
                point = gas_screening(self.config, self.control.states, now) if self.control.connected else {}
                self.cv_warmup.screen(point, now)
                self.cv_maintenance.evidence.screen(point, now)
            sample = cv_sample(self.config, self.control, plan, now)
            if prepare:
                self.cv_warmup.prepare(sample, view, plan, self.heating.action(plan, now), now)
            else:
                self.cv_warmup.observe(sample, view, plan, self.control.records(), now)
                self.cv_maintenance.observe(sample, view, plan, self.control.records(), now)
        except Exception:
            self.cv_warmup.reset()
            self.cv_maintenance.session = None

    def _prepare_startup(self):
        # Observe immediately before the existing controller acts; never issue a command here.
        try:
            now = time.time()
            plan, view = self.heating.view(self.config, now), self.schedule.view(now)
            states = self.control.states
            sample = meter_context(self.config, states, plan,
                                   measurement(self.config, states, now), now)
            self.startup_energy.prepare(sample, view, plan, self.heating.action(plan, now), now)
        except Exception:
            self.startup_energy.reset()

    def _energy_advice(self):
        # Advice failure must not interrupt the thermostat or device protection.
        try:
            now = time.time()
            states = self.control.states
            plan = self.heating.view(self.config, now)
            view = self.schedule.view(now)
            self.startup_sample = meter_context(self.config, states, plan,
                                    measurement(self.config, states, now), now)
            self.startup_energy.observe(self.startup_sample, view, plan,
                                       self.control.records(), now)
            self.warmup_sample = energy_context(self.config, states, plan,
                                    measurement(self.config, states, now), now, steady=False)
            self.warmup_energy.observe(self.warmup_sample, view, plan, now)
            sample = energy_context(self.config, states, plan,
                                    measurement(self.config, states, now), now)
            outlook = read_outlook(states, now, self.control.connected and self.connection == 'connected')
            idle_sample = idle_context(self.config, states, plan,
                                      measurement(self.config, states, now), view, now)
            if not self.control.connected or self.connection != 'connected':
                idle_sample = None
            selected_source = (self.start_intent.current or {}).get('source', 'beneden')
            own = self.heating.data['owned'].get(selected_source, {})
            active = own.get('energy_start')
            if active and self.start_intent.current and active['created_at'] == self.start_intent.current['created_at']:
                record = next((c for c in self.control.records() if c['id'] == own['command']), {})
                if record.get('status') in ('awaiting_feedback', 'confirmed'):
                    self.start_intent.started(own['command'])
                else:
                    self.start_intent.cancel('Startopdracht niet bevestigd; geen automatische herhaling.')
            self.energy_proposals.fixed_start = self.start_intent.check(idle_sample, view, plan, now)
            self.energy_proposals.fixed_source = (selected_source
                if self.energy_proposals.fixed_start is not None else None)
            window = view.get('current') or view.get('next') or {}
            cv_query = cv_sample(self.config, self.control, plan, now, target=window.get('target'))
            auxiliary = self.auxiliary_history
            parameters = cv_assumptions(self.config)
            modeled_id = (auxiliary.identity if auxiliary.current.get('status') == 'estimated'
                          and auxiliary.last is not None and 0 <= now-auxiliary.last <= 60 else None)
            tail_until, tail_power = now, 0
            if (parameters and modeled_id and auxiliary.current.get('phase') == 'postrun'
                    and not auxiliary.review.tail_is_dhw and auxiliary.off_since is not None):
                tail_power = parameters['postrun_power_w']
                tail_until = auxiliary.off_since + parameters['postrun_seconds']
            cv_context = dict(sample=cv_query, warmup=self.cv_warmup, maintenance=self.cv_maintenance,
                              gas_price=self.config.get('gas_price'), modeled_source_id=modeled_id,
                              prior_tail_until=tail_until, prior_tail_power_w=tail_power,
                              unsettled_space_load=(auxiliary.current.get('phase') == 'active'
                                and gas_screening(self.config, states, now).get('active') is not True))
            self.energy_proposals.tick(sample, view, plan, outlook, now,
                warmup=self.warmup_energy, warmup_sample=self.warmup_sample,
                startup=self.startup_energy, idle_sample=idle_sample, states=states, cv_context=cv_context)
            self.energy_selection.tick(states, self.energy_proposals, now,
                self.control.connected and self.connection == 'connected')
            self.start_intent.capture(self.energy_selection, self.energy_proposals,
                                      idle_sample, view, plan, now)
        except Exception:
            self.startup_sample = None
            self.start_intent.cancel('Energieadvies tijdelijk niet beschikbaar.')
            self.energy_selection.withdraw('Energieadvies tijdelijk niet beschikbaar.')
            self.startup_energy.reset()
            self.warmup_sample = None
            self.warmup_energy.session = None
            self.energy_proposals.model.session = None
            self.energy_proposals.standby.observe(None, time.time())
            self.energy_proposals.withdraw('Verbruiksadvies tijdelijk niet beschikbaar.')

    def _notify_health(self):
        # Reporting must never change heating or command handling.
        try:
            self.notifications.observe('ha_connection', self.connection == 'disconnected',
                self.error or 'HA-verbinding en gegevensverwerking hersteld.')
            for source in self.control.bindings:
                fault = self.heating.data['faults'].get(source)
                self.notifications.observe('heating_' + source, bool(fault),
                    'Verwarming ' + source + ': ' + (fault or 'blokkering opgeheven.'))
        except Exception:
            pass

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
        weather['hourly'] = self.weather.hourly.view(time.time())
        weather['forecast'] = forecast_view(weather.get('forecast'), time.time(),
            'HA-verbinding niet actueel.' if self.connection != 'connected' or age is None or age > self.config['stale_seconds'] else None)
        data['sources'] = self.control.sources(time.time(), self.config['stale_seconds'])
        data['commands'] = self.control.records()[:20]
        with self.control.lock:
            data['schedule'] = self.schedule.view(time.time())
            data['heating'] = self.heating.view(self.config, time.time())
            data['energy_outlook'] = read_outlook(self.control.states, time.time(),
                self.control.connected and self.connection == 'connected' and age is not None
                and 0 <= age <= self.config['stale_seconds'])
            data['energy_assessment'] = read_assessment(self.control.states, time.time(),
                self.control.connected and self.connection == 'connected' and age is not None
                and 0 <= age <= self.config['stale_seconds'])
            data['energy_proposals'] = self.energy_proposals.view(time.time())
            data['warmup_energy'] = self.warmup_energy.view(self.warmup_sample, time.time())
            data['startup_energy'] = self.startup_energy.view(self.startup_sample, time.time())
            cv_now = time.time()
            cv_window = data['schedule'].get('current') or data['schedule'].get('next') or {}
            cv_query = cv_sample(self.config, self.control, data['heating'], cv_now,
                                 target=cv_window.get('target'))
            data['cv_warmup'] = self.cv_warmup.view(
                cv_now, cv_query,
                gas_price=self.config.get('gas_price'))
            data['cv_maintenance'] = self.cv_maintenance.view(
                cv_query, cv_now)
            data['energy_selection'] = self.energy_selection.view(time.time())
            data['start_intent'] = self.start_intent.view(time.time())
        data['control_mode'] = ('automatic_heating' if data['heating']['enabled']
                                else 'bathroom_timer' if data['heating']['timer']['active'] else 'comfort_input')
        for zone in data['zones']:
            zone['reason'] = ('Monitoring; verwarmd via cv, zonder actieve ruimteregeling.'
                              if zone['settings'].get('monitor_only') else
                              data['heating']['zones'][zone['id']]['reason'])
        data['csrf_token'] = self.csrf_token
        data.update(connection=self.connection, error=self.error, age_seconds=age,
                    retention_days=self.config['retention_days'],
                    stale=age is None or age > self.config['stale_seconds'])
        return data


def handler(runtime, ingress, tablet_only=False):
    web = Path(__file__).parent / 'web'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def permitted(self):
            if ingress and self.client_address[0] != '172.30.32.2':
                self.send_error(403)
                return False
            if tablet_only and not authorized(self.headers.get('Authorization', ''),
                                              runtime.config.get('tablet_password', '')):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="PicoT tablet", charset="UTF-8"')
                self.send_header('Content-Length', '0')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return False
            return True

        def do_POST(self):
            if not self.permitted():
                return
            path = urlsplit(self.path).path
            tablet_paths = ('/api/tablet/temperature', '/api/tablet/resume')
            if tablet_only and path not in tablet_paths:
                self.send_error(404)
                return
            if path not in ('/api/settings', '/api/commands', '/api/schedule', '/api/resume', '/api/heating', '/api/heating/reset', '/api/heating/timer', *tablet_paths):
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
                    if path in tablet_paths:
                        view = tablet_view(runtime)
                        if not view['controllable']:
                            raise ValueError(view['error'])
                        if path.endswith('/temperature'):
                            runtime.schedule.set_temperature(payload, time.time())
                        else:
                            if payload != {}:
                                raise ValueError('Ongeldig hervatverzoek.')
                            runtime.schedule.resume_temperature(time.time())
                        result = tablet_view(runtime)
                    elif path == '/api/settings':
                        result = runtime.update_settings(payload)
                    elif path == '/api/commands':
                        result = {'command': runtime.control.submit(payload, runtime.config['stale_seconds'])}
                    elif path == '/api/schedule':
                        result = {'schedule': runtime.schedule.update(payload, time.time())}
                    elif path in ('/api/heating', '/api/heating/reset', '/api/heating/timer'):
                        if path.endswith('/timer'):
                            runtime.heating.update_timer(payload, runtime.config, time.time())
                        elif path.endswith('/reset'):
                            if payload != {}:
                                raise ValueError('Ongeldig vrijgaveverzoek.')
                            runtime.heating.reset_faults()
                        else:
                            runtime.heating.update(payload)
                        result = {'heating': runtime.heating.view(runtime.config, time.time())}
                    else:
                        if payload != {}:
                            raise ValueError('Ongeldig hervatverzoek.')
                        started = time.time()
                        try:
                            states = fetch_states(runtime.url, runtime.token, runtime.control.temperature_entities)
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
            if not self.permitted():
                return
            path = urlsplit(self.path).path
            if tablet_only:
                if path == '/':
                    path = '/tablet.html'
                if path not in ('/tablet.html', '/tablet.css', '/tablet.js', '/api/tablet'):
                    self.send_error(404)
                    return
            if path == '/api/tablet':
                self.send_json(200, tablet_view(runtime))
                return
            if path == '/api/building-export':
                self.export_building()
                return
            if path == '/api/snapshot':
                body = json.dumps(runtime.current(), allow_nan=False).encode()
                mime = 'application/json'
            elif path == '/api/history':
                body = json.dumps(runtime.store.history(time.time() - 86400), allow_nan=False).encode()
                mime = 'application/json'
            elif path in ('/', '/index.html', '/app.js', '/heating.js', '/climate-charts.js', '/style.css', '/tablet.html', '/tablet.css', '/tablet.js'):
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
    tablet_enabled = config.get('tablet_enabled', False)
    password = config.get('tablet_password', '')
    if tablet_enabled and (not isinstance(password, str) or len(password) < 12):
        raise ValueError('Stel voor het tablet-dashboard een wachtwoord van minimaal 12 tekens in.')
    directory = Path(args.data)
    directory.mkdir(parents=True, exist_ok=True)
    supervisor = os.environ.get('SUPERVISOR_TOKEN', '')
    rt = Runtime(config, Store(directory / 'hc.sqlite3'),
                 'http://supervisor/core/api' if supervisor else os.environ.get('HC_HA_API', 'http://127.0.0.1:8123/api'),
                 supervisor or os.environ.get('HC_HA_TOKEN', ''))
    threading.Thread(target=rt.run, daemon=True).start()
    if tablet_enabled:
        threading.Thread(target=rt.tablet_energy.run, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0' if supervisor else '127.0.0.1', args.port), handler(rt, bool(supervisor)))
    tablet_server = None
    if tablet_enabled:
        tablet_server = ThreadingHTTPServer(('0.0.0.0' if supervisor else '127.0.0.1', 8100),
                                           handler(rt, False, tablet_only=True))
        threading.Thread(target=tablet_server.serve_forever, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        rt.stop.set()
        rt.poll_now.set()
        rt.notifications.close()
        server.server_close()
        if tablet_server is not None:
            tablet_server.shutdown()
            tablet_server.server_close()


if __name__ == '__main__':
    main()
