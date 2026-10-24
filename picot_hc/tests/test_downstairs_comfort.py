"""Downstairs contract through real runtime, storage and control; fake HA transport."""
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from picot_hc.__main__ import Runtime, handler
from picot_hc.core import Store
from picot_hc.schedule import DOOR, TZ


NOW = datetime(2026, 10, 22, 18, tzinfo=TZ).timestamp()


class DownstairsComfortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text(encoding='utf-8'))
        for zone in config['zones']:
            zone.update(minimum=10, target=20, maximum=25)
        self.store = Store(Path(self.tmp.name) / 'hc.sqlite3')
        self.runtime = Runtime(config, self.store, 'http://fake/api', 'test')
        self.config = self.runtime.config
        self.schedule, self.heat, self.ctl = self.runtime.schedule, self.runtime.heating, self.runtime.control
        self.states, self.calls = {}, []
        for source in self.ctl.bindings.values():
            entity = source['entity_id']
            self.states[entity] = dict(entity_id=entity, state='off', attributes=dict(
                hvac_modes=['off', 'heat'], temperature=20, min_temp=5, max_temp=30,
                target_temp_step=.5, supported_features=1))
        for zone in self.config['zones']:
            self.states[zone['temperature']] = dict(entity_id=zone['temperature'], state='22',
                attributes={'unit_of_measurement': '°C'}, last_updated=self.stamp(NOW), last_reported=self.stamp(NOW))
        self.states[DOOR] = dict(entity_id=DOOR, state='off', attributes={})
        self.states[self.config['price_entity']] = dict(state='.25', attributes={
            'unit_of_measurement': 'EUR/kWh', 'raw_today': [dict(start=self.stamp(NOW-3600),
            end=self.stamp(NOW+86400), value=.25)]})
        self.now = NOW
        self.config['price_basis_confirmed'] = True
        self.config['confirmed_price_entity'] = self.config['price_entity']
        self.config['gas_valid_until'] = '2027-06-14'
        self.addCleanup(patch.stopall)
        patch.object(self.runtime.energy_selection.publisher, 'submit').start()
        patch.object(self.runtime.energy_execution_publisher, 'submit').start()
        patch.object(self.runtime.energy_reservation_publisher, 'submit').start()
        patch('picot_hc.control.ha_request', side_effect=self.request).start()
        patch('picot_hc.control.fetch_states', side_effect=lambda *args: copy.deepcopy(self.states)).start()
        patch('time.time', side_effect=lambda: self.now).start()
        self.ctl.observe(self.states, NOW, NOW)
        self.heat.update(dict(revision=self.heat.data['revision'], settings=dict(self.heat.data['settings'], enabled=True)))

    @staticmethod
    def stamp(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    def request(self, url, token, path, payload=None):
        if path == '/config':
            return {'unit_system': {'temperature': '°C'}}
        self.assertTrue(path.startswith('/services/'), path)
        self.calls.append((path, copy.deepcopy(payload)))
        state = self.states[payload['entity_id']]
        if 'hvac_mode' in payload:
            state['state'] = payload['hvac_mode']
        if 'temperature' in payload:
            state['attributes']['temperature'] = payload['temperature']
        if path.startswith('/services/switch/'):
            state['state'] = 'on' if path.endswith('turn_on') else 'off'
        return []

    def temperature(self, zone, value):
        entity = next(z['temperature'] for z in self.config['zones'] if z['id'] == zone)
        self.states[entity]['state'] = str(value)

    def poll(self, advance=31):
        self.now += advance
        for zone in self.config['zones']:
            self.states[zone['temperature']]['last_reported'] = self.stamp(self.now)
        self.ctl.observe(self.states, self.now, self.now)
        self.schedule.tick(self.config, self.now)
        self.heat.tick(self.config, self.now)
        return self.heat.view(self.config, self.now)

    def settings(self, **changes):
        value = dict(self.schedule.data['settings'], **changes)
        self.schedule.update(dict(revision=self.schedule.data['revision'], settings=value), self.now)

    def test_manual_thermostat_has_no_time_boundaries(self):
        self.settings(thermostat_temperature=19.5, windows=[dict(day=3, start='18:00', end='22:00', target=23, hard=True)])
        for hours in (0, 4, 12, 24, 48):
            view = self.schedule.view(NOW+hours*3600)
            self.assertEqual(view['comfort']['zones']['beneden']['request']['target'], 19.5)
            self.assertIsNone(view['next_boundary'])
            self.assertEqual(view['comfort']['horizon'], [])

    def test_schedule_owns_window_and_gap_despite_legacy_zone_values(self):
        self.settings(enabled=True, setback_temperature=17, thermostat_temperature=19,
            windows=[dict(day=3, start='18:00', end='22:00', target=20, hard=True)])
        self.config['zones'][0].update(minimum=24, target=25, maximum=26)
        view = self.schedule.view(NOW)['comfort']['zones']['beneden']
        self.assertEqual(view['request']['target'], 20)
        self.assertEqual(view['errors'], [])
        self.assertEqual(self.schedule.view(NOW+4*3600)['comfort']['zones']['beneden']['request']['target'], 17)
        self.settings(enabled=False)
        self.assertEqual(self.schedule.view(NOW)['comfort']['zones']['beneden']['request']['target'], 19)
        with self.assertRaises(ValueError):
            self.runtime.update_settings(dict(zone_id='beneden', values=dict(minimum=17, target=18, maximum=22)))

    def test_airco_maintains_and_lower_target_does_not_send_off(self):
        self.temperature('beneden', 19)
        self.poll(121)
        self.temperature('beneden', 20)
        self.poll()
        self.assertEqual(self.heat.view(self.config, self.now)['desired'], {'beneden': 20})
        self.settings(thermostat_temperature=19.5)
        self.poll()
        down = self.states[self.config['zones'][0]['device']]
        self.assertEqual((down['state'], down['attributes']['temperature']), ('heat', 19.5))
        self.assertFalse(any(body.get('hvac_mode') == 'off' for _, body in self.calls))

    def test_cv_choice_ignores_upstairs_temperature_and_target(self):
        self.states[self.config['price_entity']]['attributes']['raw_today'][0]['value'] = .9
        self.temperature('beneden', 19)
        for upstairs in ('16', '25', 'unavailable'):
            self.temperature('boven', upstairs)
            self.config['zones'][1]['target'] = None
            plan = self.poll(121)
            self.assertEqual(plan['desired'], {'cv': 20})

    def test_upstairs_only_does_not_start_cv(self):
        self.states[self.config['price_entity']]['attributes']['raw_today'][0]['value'] = .9
        self.temperature('boven', 17)
        plan = self.poll(121)
        self.assertEqual(plan['desired'], {'boven': 20})

    def test_disable_and_invalid_temperature_still_stop_owned_airco(self):
        self.temperature('beneden', 19)
        self.poll(121)
        self.temperature('beneden', 'unavailable')
        self.poll()
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')
        self.poll()
        self.temperature('beneden', 19)
        self.poll(181)
        self.heat.update(dict(revision=self.heat.data['revision'], settings=dict(self.heat.data['settings'], enabled=False)))
        self.poll()
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')

    def test_migration_imports_once_and_retains_settings_after_restart(self):
        old = copy.deepcopy(self.schedule.data)
        old['format'] = 3
        old['settings'].pop('setback_temperature')
        old['settings'].pop('thermostat_temperature')
        with self.store.connect() as db:
            db.execute('UPDATE hc_schedule SET payload=? WHERE id=1', (json.dumps(old),))
        self.config['zones'][0]['target'] = 18
        first = Runtime(self.config, self.store, 'http://fake/api', 'test')
        self.assertEqual(first.schedule.data['settings']['thermostat_temperature'], 18)
        self.assertEqual(first.schedule.data['settings']['setback_temperature'], 18)
        self.config['zones'][0]['target'] = 24
        second = Runtime(self.config, self.store, 'http://fake/api', 'test')
        self.assertEqual(second.schedule.data, first.schedule.data)

    def test_disabling_schedule_removes_old_manual_expiry(self):
        self.settings(enabled=True, windows=[dict(day=3, start='18:00', end='22:00', target=20, hard=True)])
        self.schedule.hold('beneden', 'mode', 'off', NOW, 'manual')
        self.assertEqual(self.schedule.view(NOW)['overrides'][0]['until'], NOW+4*3600)
        self.settings(enabled=False)
        self.assertIsNone(self.schedule.view(NOW+5*3600)['overrides'][0]['until'])

    def test_unknown_target_does_not_invent_heat_and_bad_save_rolls_back(self):
        self.settings(thermostat_temperature=None)
        self.temperature('beneden', 10)
        self.assertEqual(self.poll(121)['desired'], {})
        before = copy.deepcopy(self.schedule.data)
        for value in (True, 4, 36, float('nan')):
            with self.assertRaises(ValueError):
                self.settings(thermostat_temperature=value)
        with patch.object(self.schedule, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.settings(thermostat_temperature=21)
        self.assertEqual(before, self.schedule.data)

    def test_schedule_end_lowers_setpoint_without_power_cycle(self):
        self.settings(enabled=True, setback_temperature=17,
            windows=[dict(day=3, start='18:00', end='22:00', target=20, hard=True)])
        self.temperature('beneden', 19)
        self.poll(121)
        self.poll()  # Confirm the start before advancing to the window boundary.
        self.temperature('beneden', 20)
        self.poll(NOW+4*3600-self.now)
        state = self.states[self.config['zones'][0]['device']]
        self.assertEqual((state['state'], state['attributes']['temperature']), ('heat', 17))
        self.assertFalse(any(body.get('hvac_mode') == 'off' for _, body in self.calls))

    def test_manual_off_is_respected_while_maintaining(self):
        self.temperature('beneden', 19)
        self.poll(121)
        self.poll()
        self.states[self.config['zones'][0]['device']]['state'] = 'off'
        count = len(self.calls)
        self.poll()
        self.poll(600)
        self.assertEqual(len(self.calls), count)
        self.assertNotIn('beneden', self.heat.data['owned'])

    def test_schedule_api_accepts_central_settings_and_checks_csrf(self):
        # Exercise the real HTTP handler with byte streams; no network socket.
        def post(path, payload, csrf):
            handler_type = handler(self.runtime, False)
            endpoint = handler_type.__new__(handler_type)
            body = json.dumps(payload).encode()
            endpoint.path = path
            endpoint.client_address = ('127.0.0.1', 0)
            endpoint.headers = Message()
            endpoint.headers['Content-Type'] = 'application/json'
            endpoint.headers['Content-Length'] = str(len(body))
            endpoint.headers['X-HC-CSRF'] = csrf
            endpoint.rfile, endpoint.wfile = io.BytesIO(body), io.BytesIO()
            statuses = []
            endpoint.send_response = statuses.append
            endpoint.send_error = lambda status, *args: statuses.append(status)
            endpoint.send_header = lambda *args: None
            endpoint.end_headers = lambda: None
            endpoint.do_POST()
            return statuses[0], endpoint.wfile.getvalue()
        payload = dict(revision=self.schedule.data['revision'],
            settings=dict(self.schedule.data['settings'], thermostat_temperature=19.5))
        self.assertEqual(post('/api/schedule', payload, 'wrong')[0], 403)
        status, body = post('/api/schedule', payload, self.runtime.csrf_token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['schedule']['settings']['thermostat_temperature'], 19.5)
        self.assertEqual(post('/api/settings', dict(zone_id='beneden', values=dict(minimum=17,
            target=20, maximum=22)), self.runtime.csrf_token)[0], 400)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
