"""Remeha-style OFF ignores temperature requests; mode and target need feedback."""
import copy
from unittest.mock import patch

import test_heating
from test_heating_local import LocalHeatingFixture
from picot_hc.__main__ import Runtime

NOW = test_heating.NOW


class CVModeSequenceTests(LocalHeatingFixture):
    __test__ = True

    def server(self, cls):
        return 'http://ha.invalid'

    def setUp(self):
        super().setUp()
        self.cv_ready()
        cv = self.states[self.config['cv']]
        cv['attributes'].update(temperature=None, preset_mode='anti_frost', hvac_action='off')
        self.price(.90)
        self.config['gas_valid_until'] = '2027-01-01'
        self.allow_mode = True
        self.mode_target = 6
        self.reject_temperature = False

        def request(url, token, path, payload=None):
            if path == '/config':
                return {'unit_system': {'temperature': '�C'}}
            self.calls.append((path, copy.deepcopy(payload)))
            state = self.states[payload['entity_id']]
            attrs = state['attributes']
            if payload['entity_id'] == self.config['cv']:
                # Mirror Remeha Home: set_temperature ignores hvac_mode and OFF.
                if path.endswith('/set_temperature'):
                    if state['state'] == 'heat' and not self.reject_temperature:
                        attrs['temperature'] = payload['temperature']
                elif path.endswith('/set_hvac_mode') and self.allow_mode:
                    state['state'] = payload['hvac_mode']
                    attrs.update(temperature=self.mode_target, preset_mode='manual', hvac_action='idle')
            else:
                if 'hvac_mode' in payload:
                    state['state'] = payload['hvac_mode']
                if 'temperature' in payload:
                    attrs['temperature'] = payload['temperature']
            return []

        patcher = patch('picot_hc.control.ha_request', side_effect=request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_off_then_confirmed_heat_then_temperature(self):
        self.enable()
        first = self.poll(NOW+121)
        self.assertEqual(self.calls, [('/services/climate/set_hvac_mode',
                                      {'entity_id': self.config['cv'], 'hvac_mode': 'heat'})])
        self.assertTrue(first['sources']['cv']['pending'])
        self.assertEqual(self.states[self.config['cv']]['attributes']['temperature'], 6)
        self.poll(NOW+152)
        self.assertEqual(self.calls[-1][0], '/services/climate/set_temperature')
        self.assertEqual(self.calls[-1][1]['temperature'], 20)
        final = self.poll(NOW+183)
        self.assertFalse(final['faults'])
        self.assertFalse(self.runtime.schedule.view(NOW+183)['overrides'])
        self.assertEqual(self.ctl.records()[0]['status'], 'confirmed')

    def test_pending_mode_is_not_repeated_and_timeout_off_releases_airco(self):
        self.allow_mode = False
        self.enable()
        self.poll(NOW+121)
        self.poll(NOW+152)
        self.assertEqual(len(self.calls), 1)
        self.poll(NOW+422)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][1]['entity_id'], self.config['zones'][0]['device'])
        self.assertIn('cv', self.heat.data['faults'])
        self.assertFalse(any(p.get('temperature') == 15 for _, p in self.calls))
        self.poll(NOW+453)
        self.assertEqual(len(self.calls), 2)

    def test_stale_or_unknown_cv_never_releases_airco(self):
        self.allow_mode = False
        self.enable()
        self.poll(NOW+121)
        self.states[self.config['cv']]['state'] = 'unavailable'
        self.poll(NOW+422)
        self.assertEqual(len(self.calls), 1)
        self.states[self.config['cv']]['state'] = 'off'
        with patch('time.time', return_value=NOW+600):
            self.ctl.connected = False
            self.heat.tick(self.config, NOW+600)
        self.assertEqual(len(self.calls), 1)

    def test_restart_does_not_repeat_unconfirmed_mode(self):
        self.allow_mode = False
        self.enable()
        self.poll(NOW+121)
        with patch('time.time', return_value=NOW+130):
            other = Runtime(self.config, self.store, self.url, 'fake-secret')
        self.runtime, self.heat, self.ctl = other, other.heating, other.control
        self.poll(NOW+152)
        self.poll(NOW+280)  # Existing closed-door startup delay still applies after restart.
        self.assertEqual(sum(p['entity_id'] == self.config['cv'] for _, p in self.calls), 1)
        self.assertEqual(self.calls[-1][1]['entity_id'], self.config['zones'][0]['device'])

    def test_manual_off_between_steps_is_respected(self):
        self.enable()
        self.poll(NOW+121)
        self.runtime.schedule.hold('cv', 'mode', 'off', NOW+140, 'Manual off')
        self.states[self.config['cv']]['state'] = 'off'
        self.poll(NOW+152)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.runtime.schedule.view(NOW+152)['overrides'])

    def test_disabled_between_steps_finishes_at_15(self):
        self.enable()
        self.poll(NOW+121)
        self.heat.update(dict(revision=1, settings=dict(self.heat.data['settings'], enabled=False)))
        self.poll(NOW+152)
        self.assertEqual(self.calls[-1][1]['temperature'], 15)
        self.poll(NOW+183)
        self.assertTrue(self.heat.data['owned']['cv']['standby'])
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))

    def test_late_mode_confirmation_stops_airco_before_cv_target(self):
        self.allow_mode = False
        self.enable()
        self.poll(NOW+121)
        self.poll(NOW+422)
        self.poll(NOW+453)
        cv = self.states[self.config['cv']]
        cv['state'] = 'heat'
        cv['attributes'].update(temperature=6, preset_mode='manual', hvac_action='idle')
        self.poll(NOW+760)
        self.assertEqual(self.calls[-1][1], {'entity_id': self.config['zones'][0]['device'], 'hvac_mode': 'off'})
        self.poll(NOW+791)
        self.assertEqual(self.calls[-1][1]['entity_id'], self.config['cv'])
        self.assertEqual(self.calls[-1][1]['temperature'], 20)

    def test_restored_setpoint_at_mode_confirmation_is_not_a_manual_hold(self):
        self.states[self.config['cv']]['attributes']['temperature'] = 20
        self.enable()
        self.poll(NOW+121)
        self.poll(NOW+152)
        self.assertFalse(self.runtime.schedule.view(NOW+152)['overrides'])
        self.assertEqual(self.calls[-1][1]['temperature'], 20)
        self.poll(NOW+183)
        self.states[self.config['cv']]['attributes']['temperature'] = 21
        self.poll(NOW+214)
        self.assertTrue(self.runtime.schedule.view(NOW+214)['overrides'])

    def test_failed_legacy_temperature_request_off_is_not_replayed(self):
        self.enable()
        with patch('time.time', return_value=NOW+121):
            command = self.ctl.submit(dict(request_id='legacy-command-0001', source='cv',
                field='heating', value=20), 120, origin='schedule')
        self.heat.data['owned']['cv'] = dict(command=command['id'], since=NOW+121)
        self.poll(NOW+422)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][1]['entity_id'], self.config['zones'][0]['device'])
        self.assertIn('cv', self.heat.data['faults'])

    def test_new_mode_request_is_not_sent_when_manual_change_arrives_in_guard(self):
        self.enable()
        def manual_before_write(*args, **kwargs):
            self.runtime.schedule.hold('cv', 'mode', 'off', NOW+121, 'User changed just before write')
            return copy.deepcopy(self.states)
        with patch('picot_hc.control.fetch_states', side_effect=manual_before_write):
            self.poll(NOW+121)
        self.assertEqual(self.calls, [])


for _name in dir(test_heating.HeatingTests):
    if _name.startswith('test_') and _name not in CVModeSequenceTests.__dict__:
        setattr(CVModeSequenceTests, _name, None)
