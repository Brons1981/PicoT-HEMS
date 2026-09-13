import copy
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from picot_hc.__main__ import handler
from datetime import datetime
from unittest.mock import patch

from test_control import ControlFixture
from picot_hc.__main__ import Runtime
from picot_hc.schedule import DOOR, TZ, moments, validate_settings

NOW = datetime(2026, 9, 14, 8, tzinfo=TZ).timestamp()


class ScheduleTests(ControlFixture):
    def setUp(self):
        super().setUp()
        self.scheduler = self.runtime.schedule
        self.config = self.runtime.config
        self.config['zones'][0].update(temperature='sensor.downstairs', minimum=16, maximum=24)
        self.states['sensor.downstairs'] = dict(entity_id='sensor.downstairs', state='19', attributes={'unit_of_measurement':'°C'})
        self.states[DOOR] = dict(entity_id=DOOR, state='off', attributes={})
        self.settings = dict(enabled=True, source='cv', entries=[
            dict(day=day, time=clock, temperature=temp)
            for day in range(7) for clock, temp in [('06:00', 21.5), ('22:00', 16)]],
            door_open_seconds=60, door_close_seconds=120, sensor_max_age_seconds=900)
        self.apply = True

    def observe(self, at=NOW):
        self.states['sensor.downstairs']['last_reported'] = datetime.fromtimestamp(at, TZ).isoformat()
        with patch('time.time', return_value=at):
            self.ctl.observe(self.states, at, at)

    def enable(self):
        self.observe()
        self.scheduler.update(dict(revision=0, settings=self.settings), NOW)

    def tick(self, at=NOW):
        with patch('time.time', return_value=at):
            self.scheduler.tick(self.config, at)

    def test_default_off_and_temperature_gate(self):
        self.observe(); self.tick()
        self.assertEqual(self.calls, [])
        self.scheduler.update(dict(revision=0, settings=self.settings), NOW)
        self.config['zones'][0]['temperature'] = ''
        self.tick()
        self.assertEqual(self.calls, [])
        self.assertIn('temperatuursensor', self.scheduler.reason)

    def test_schedule_combined_command_feedback_no_repeat(self):
        self.enable(); self.tick()
        self.assertEqual(self.calls, [('/api/services/climate/set_temperature',
            dict(entity_id=self.config['cv'], temperature=21.5, hvac_mode='heat'))])
        self.tick(NOW+1)
        self.assertEqual(len(self.calls), 1)
        self.observe(NOW+2); self.tick(NOW+2)
        self.assertIsNone(self.scheduler.data['override'])
        self.assertEqual(self.ctl.records()[0]['status'], 'confirmed')
        self.assertEqual(len(self.calls), 1)

    def test_manual_change_and_resume_at_next_slot(self):
        self.enable(); self.tick(); self.observe(NOW+1)
        self.states[self.config['cv']]['attributes']['temperature'] = 19
        self.observe(NOW+10); self.tick(NOW+11)
        override = self.scheduler.view(NOW+11)['override']
        self.assertIsNotNone(override)
        next_time = datetime(2026, 9, 14, 22, tzinfo=TZ).timestamp()
        self.assertEqual(override['until'], next_time)
        self.assertEqual(len(self.calls), 1)
        self.observe(next_time); self.tick(next_time)
        self.assertIsNone(self.scheduler.data['override'])
        self.assertEqual(self.calls[-1][1]['temperature'], 16)

    def test_manual_return_to_previous_value_is_detected_after_confirmation(self):
        self.enable(); self.tick(); self.observe(NOW+1)
        self.states[self.config['cv']]['attributes']['temperature'] = 20
        self.observe(NOW+2)
        self.assertIsNotNone(self.scheduler.data['override'])

    def test_delayed_own_feedback_does_not_pause(self):
        self.apply = False
        self.enable(); self.tick()
        self.observe(NOW+50); self.tick(NOW+50)
        self.assertIsNone(self.scheduler.data['override'])
        self.assertEqual(len(self.calls), 1)
        self.states[self.config['cv']]['state'] = 'heat'
        self.observe(NOW+60)
        self.states[self.config['cv']]['attributes']['temperature'] = 21.5
        self.observe(NOW+90)
        self.assertIsNone(self.scheduler.data['override'])
        self.assertEqual(self.ctl.records()[0]['status'], 'confirmed')

    def test_mode_and_preset_override_but_activity_does_not(self):
        self.enable(); self.tick(); self.observe(NOW+1)
        self.states[self.config['cv']]['attributes']['hvac_action'] = 'heating'
        self.observe(NOW+2)
        self.assertIsNone(self.scheduler.data['override'])
        self.states[self.config['cv']]['state'] = 'off'
        self.observe(NOW+3)
        self.assertIsNotNone(self.scheduler.data['override'])
        self.scheduler.resume(NOW+4); self.tick(NOW+4); self.observe(NOW+5)
        self.states[self.config['cv']]['attributes']['preset_mode'] = 'manual'
        self.observe(NOW+6)
        self.states[self.config['cv']]['attributes']['preset_mode'] = 'clock_program_1'
        self.observe(NOW+7)
        self.assertIsNotNone(self.scheduler.data['override'])

    def test_hc_manual_command_pauses_before_next_poll(self):
        self.enable(); self.tick(); self.observe(NOW+1)
        with patch('time.time', return_value=NOW+2):
            self.submit(self.payload('cv', 'temperature', 19.5))
        self.assertIn('vanuit HC', self.scheduler.data['override']['reason'])
        self.observe(NOW+3); self.tick(NOW+3)
        self.assertEqual(len(self.calls), 2)
        self.scheduler.resume(NOW+4); self.tick(NOW+4)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[-1][1]['temperature'], 21.5)

    def test_fresh_pre_dispatch_read_detects_manual_change(self):
        self.enable()
        self.states[self.config['cv']]['attributes']['temperature'] = 19
        # The cached observation still says 20. Submit must notice the new HA value.
        self.tick(NOW+1)
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(self.scheduler.data['override'])

    def test_timeout_blocks_new_slot_until_explicit_resume(self):
        self.apply = False
        self.enable(); self.tick(); self.observe(NOW+301)
        next_time = datetime(2026, 9, 14, 22, tzinfo=TZ).timestamp()
        self.observe(next_time); self.tick(next_time)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('hervatten', self.scheduler.reason)
        self.scheduler.resume(next_time+1); self.tick(next_time+1)
        self.assertEqual(len(self.calls), 2)

    def test_restart_retains_settings_pause_and_no_replay(self):
        self.enable(); self.tick(); self.observe(NOW+1)
        self.scheduler.pause('Handmatig', NOW+2)
        with patch('time.time', return_value=NOW+3):
            other = Runtime(self.config, self.store, self.url, 'fake-secret')
        self.assertEqual(other.schedule.data['settings'], self.settings)
        self.assertEqual(other.schedule.data['override']['reason'], 'Handmatig')
        self.assertEqual(len(self.calls), 1)

    def test_airco_door_delays_and_unknown_do_not_mean_closed(self):
        self.settings['source'] = 'beneden'
        self.enable(); self.tick()
        self.assertEqual(self.calls, [])
        self.observe(NOW+121); self.tick(NOW+121); self.observe(NOW+122)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'heat')
        self.states[DOOR]['state'] = 'on'
        self.observe(NOW+130); self.tick(NOW+131)
        self.assertEqual(len(self.calls), 1)
        self.observe(NOW+191); self.tick(NOW+191); self.observe(NOW+192)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')
        self.states[DOOR]['state'] = 'unknown'
        self.observe(NOW+200); self.tick(NOW+200)
        self.assertEqual(len(self.calls), 2)
        self.states[DOOR]['state'] = 'off'
        self.observe(NOW+210); self.tick(NOW+220)
        self.assertEqual(len(self.calls), 2)
        self.observe(NOW+331); self.tick(NOW+331)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'heat')
        self.assertIsNone(self.scheduler.data['override'])

    def test_door_stop_preempts_unconfirmed_heating(self):
        self.settings['source'] = 'beneden'
        self.apply = False
        self.enable()
        self.observe(NOW+121); self.tick(NOW+121)
        self.states[DOOR]['state'] = 'on'
        self.states['sensor.downstairs']['state'] = 'unavailable'
        self.observe(NOW+130)
        self.observe(NOW+191); self.tick(NOW+191)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')
        self.assertEqual(self.ctl.records()[1]['status'], 'superseded')
        self.tick(NOW+192)
        self.assertEqual(len(self.calls), 2)

    def test_bad_limits_and_unavailable_never_start(self):
        self.enable()
        self.config['zones'][0]['maximum'] = 20
        self.tick(); self.assertEqual(self.calls, [])
        self.config['zones'][0]['maximum'] = 24
        self.states['sensor.downstairs']['state'] = 'unavailable'
        self.observe(NOW+1); self.tick(NOW+1)
        self.assertEqual(self.calls, [])

    def test_stale_temperature_blocks_dispatch(self):
        self.enable()
        self.states['sensor.downstairs']['last_reported'] = datetime.fromtimestamp(NOW-901, TZ).isoformat()
        with patch('time.time', return_value=NOW):
            self.ctl.observe(self.states, NOW, NOW)
        self.tick()
        self.assertEqual(self.calls, [])
        self.assertIn('verouderd', self.scheduler.reason)

    def test_other_source_and_backwards_clock_block_new_heating(self):
        self.enable()
        self.states[self.config['zones'][0]['device']]['state'] = 'heat'
        # An already-active other source is not silently switched off.
        self.scheduler.data['baseline'] = {}
        self.observe(NOW+1); self.tick(NOW+1)
        self.assertEqual(self.calls, [])
        self.assertIn('andere warmtebron', self.scheduler.reason)
        self.observe(NOW-10)
        self.assertIn('klok', self.scheduler.data['fault'])

    def test_storage_failure_prevents_schedule_dispatch(self):
        self.enable()
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_schedule BEFORE INSERT ON hc_schedule BEGIN SELECT RAISE(FAIL, 'disk'); END")
        with self.assertRaises(Exception):
            self.tick()
        self.assertEqual(self.calls, [])

    def test_schedule_and_resume_http_require_csrf_and_ingress(self):
        url = self.server(handler(self.runtime, False))
        payload = json.dumps(dict(revision=0, settings=self.settings)).encode()
        for path, body in [('/api/schedule', payload), ('/api/resume', b'{}')]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url+path, data=body, headers={'Content-Type':'application/json'}))
            self.assertEqual(error.exception.code, 403)
        headers = {'Content-Type':'application/json', 'X-HC-CSRF':self.runtime.csrf_token}
        result = json.load(urlopen(Request(url+'/api/schedule', data=payload, headers=headers)))
        self.assertTrue(result['schedule']['settings']['enabled'])
        self.assertEqual(self.calls, [])
        self.scheduler.pause('Test', NOW)
        result = json.load(urlopen(Request(url+'/api/resume', data=b'{}', headers=headers)))
        self.assertIsNone(result['schedule']['override'])
        self.assertEqual(self.calls, [])  # The collector owns execution, never the HTTP handler.
        ingress = self.server(handler(self.runtime, True))
        for path, body in [('/api/schedule', payload), ('/api/resume', b'{}')]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(ingress+path, data=body, headers=headers))
            self.assertEqual(error.exception.code, 403)

    def test_week_boundary_dst_and_validation(self):
        settings = copy.deepcopy(self.settings)
        settings['entries'] = [dict(day=0, time='06:00', temperature=20)]
        previous, following = moments(settings, NOW)
        self.assertEqual(datetime.fromtimestamp(previous['at'], TZ).hour, 6)
        self.assertEqual(datetime.fromtimestamp(following['at'], TZ).day, 21)
        settings['entries'] = [dict(day=6, time='02:30', temperature=20)]
        spring = datetime(2026, 3, 29, 4, tzinfo=TZ).timestamp()
        previous, following = moments(settings, spring)
        self.assertEqual(datetime.fromtimestamp(previous['at'], TZ).day, 22)
        self.assertEqual(datetime.fromtimestamp(following['at'], TZ).day, 5)
        autumn = datetime(2026, 10, 25, 2, 45, tzinfo=TZ, fold=1).timestamp()
        previous, following = moments(settings, autumn)
        self.assertEqual(datetime.fromtimestamp(previous['at'], TZ).fold, 0)
        self.assertEqual(datetime.fromtimestamp(following['at'], TZ).day, 1)
        for bad in [dict(day=7,time='06:00',temperature=20), dict(day=1,time='24:00',temperature=20),
                    dict(day=1,time='06:00',temperature=float('nan'))]:
            settings['entries'] = [bad]
            with self.assertRaises(ValueError): validate_settings(settings)
        with self.assertRaises(ValueError):
            self.scheduler.update(dict(revision=99, settings=self.settings), NOW)
