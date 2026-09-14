"""Comfort contract, persistence and manual precedence; fake HA is a real HTTP server."""
import copy
import json
import sqlite3
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_control import ControlFixture
from picot_hc.__main__ import Runtime, handler
from picot_hc.schedule import TZ, occurrences, validate_settings

NOW = datetime(2026, 9, 14, 8, tzinfo=TZ).timestamp()


def window(day=0, start='18:00', end='22:00', target=20, minimum=20, maximum=20, hard=True):
    return dict(day=day, start=start, end=end, target=target, hard=hard)


class ScheduleTests(ControlFixture):
    def setUp(self):
        super().setUp()
        self.scheduler = self.runtime.schedule
        self.config = self.runtime.config
        self.config['zones'][0].update(minimum=16, target=18, maximum=22)
        self.config['zones'][1].update(minimum=16, target=18, maximum=20)
        self.config['zones'][2].update(minimum=16, target=21, maximum=24)
        self.settings = dict(enabled=True, optimization_band=1, windows=[window()], door_open_seconds=60,
                             door_close_seconds=120, sensor_max_age_seconds=900)
        self.apply = True

    def observe(self, at=NOW):
        with patch('time.time', return_value=at):
            self.ctl.observe(self.states, at, at)

    def enable(self):
        self.observe()
        self.scheduler.update(dict(revision=0, settings=self.settings), NOW)

    def test_hard_deadline_and_flexible_night_are_source_independent(self):
        self.settings['windows'].append(window(start='22:00', end='06:00', target=17, minimum=17, maximum=18, hard=False))
        self.enable()
        view = self.scheduler.view(NOW)
        self.assertNotIn('source', view['settings'])
        self.assertIsNone(view['comfort']['selected_sources'])
        deadline = view['comfort']['deadlines'][0]
        self.assertEqual(deadline['required_at'], datetime(2026, 9, 14, 18, tzinfo=TZ).timestamp())
        self.assertEqual(deadline['minimum'], 20)
        night = datetime(2026, 9, 14, 23, tzinfo=TZ).timestamp()
        request = self.scheduler.view(night)['comfort']['zones']['beneden']['request']
        self.assertEqual((request['target'], request['minimum'], request['maximum'], request['hard']), (17,16,18,False))

    def test_central_band_and_exact_comfort(self):
        self.settings['optimization_band'] = 1.5
        self.settings['windows'] = [window(start='08:00',end='18:00',target=17,hard=False), window()]
        self.enable()
        request = self.scheduler.view(NOW)['current']
        self.assertEqual((request['minimum'],request['maximum']),(15.5,18.5))
        request = self.scheduler.view(NOW+10*3600)['current']
        self.assertEqual((request['minimum'],request['maximum']),(20,20))
        for band in [True,-1,6,float('nan')]:
            with self.assertRaises(ValueError):
                validate_settings(dict(self.settings,optimization_band=band))
        self.assertEqual(self.calls,[])

    def test_dev10_migration_preserves_windows_and_manual_constraints(self):
        self.enable()
        old = copy.deepcopy(self.scheduler.data)
        old['format'] = 2
        del old['settings']['optimization_band']
        old['settings']['windows'][0].update(minimum=20,maximum=21)
        old['overrides'] = {'example':dict(until=None,source='boven',command_id=None)}
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)',(json.dumps(old),))
        other = Runtime(self.config,self.store,self.url,'fake-secret')
        data = other.schedule.data
        self.assertFalse(data['settings']['enabled'])
        self.assertEqual(data['settings']['windows'],[window()])
        self.assertEqual(data['overrides'],old['overrides'])
        self.assertTrue(data['migration'])
        again = Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertEqual(again.schedule.data,data)
        with self.store.connect() as db:
            archived=json.loads(db.execute('SELECT payload FROM hc_schedule_archive WHERE id=2').fetchone()[0])
        self.assertEqual(archived,old)
        self.assertEqual(self.calls,[])

    def test_no_dispatch_on_enable_tick_transition_restart_or_resume(self):
        self.enable()
        for at in [NOW, NOW+1, NOW+36000, NOW+72000]:
            self.scheduler.tick(self.config, at)
        self.scheduler.resume(NOW)
        other = Runtime(self.config, self.store, self.url, 'fake-secret')
        other.collect()
        self.assertEqual(self.calls, [])
        self.assertEqual(other.current()['schedule']['comfort']['planner_status'], 'not_implemented')

    def test_fixed_values_above_and_bathroom_and_humidity(self):
        self.enable()
        for at in [NOW, NOW+36000, NOW+86400]:
            zones = self.scheduler.view(at)['comfort']['zones']
            self.assertEqual(zones['boven']['request']['target'], 18)
            self.assertEqual(zones['badkamer']['request']['target'], 21)
            self.assertEqual(zones['boven']['request']['kind'], 'fixed')
            self.assertEqual(zones['boven']['request']['minimum'], 16)
            self.assertEqual(zones['boven']['request']['maximum'], 20)
            self.assertEqual(zones['boven']['humidity'], dict(min=40,target=50,max=60))
        # Editing a comfort target never forces an appliance.
        self.runtime.update_settings(dict(zone_id='boven', values=dict(minimum=16,target=19,maximum=20)))
        self.assertEqual(self.scheduler.view(NOW)['comfort']['zones']['boven']['request']['target'], 19)
        self.assertEqual(self.scheduler.view(NOW)['overrides'], [])

    def test_gap_uses_configured_fallback_without_inventing_temperature(self):
        self.enable()
        self.assertEqual(self.scheduler.view(NOW)['comfort']['zones']['beneden']['request']['target'], 18)
        self.config['zones'][0]['target'] = None
        self.assertIsNone(self.scheduler.view(NOW)['comfort']['zones']['beneden']['request'])

    def test_weekend_full_day_and_end_exclusive(self):
        self.settings['windows'] = [window(day=5,start='00:00',end='24:00'), window(day=6,start='00:00',end='24:00')]
        self.enable()
        for day in [19,20]:
            at = datetime(2026,9,day,12,tzinfo=TZ).timestamp()
            self.assertEqual(self.scheduler.view(at)['current']['target'], 20)
        monday = datetime(2026,9,21,0,tzinfo=TZ).timestamp()
        self.assertIsNone(self.scheduler.view(monday)['current'])

    def test_manual_temperature_forces_shared_cv_until_boundary(self):
        self.enable()
        self.states[self.config['cv']]['state'] = 'heat'
        self.observe(NOW+1)
        with patch('time.time', return_value=NOW+2):
            command = self.submit(self.payload('cv','temperature',19.5))
        hold = self.scheduler.view(NOW+2)['overrides'][0]
        self.assertTrue(hold['forced_source'])
        self.assertFalse(hold['confirmed'])
        self.assertEqual(hold['temperature'],19.5)
        self.observe(NOW+3)
        view = self.scheduler.view(NOW+3)
        hold = view['overrides'][0]
        self.assertTrue(hold['confirmed'])
        self.assertEqual(hold['command_id'],command['id'])
        self.assertEqual(hold['zones'],['beneden','boven'])
        self.assertEqual(len(view['comfort']['zones']['boven']['source_constraints']),1)
        self.assertEqual(self.scheduler.view(hold['until'])['overrides'], [])
        self.assertEqual(len(self.calls),1)

    def test_external_temperature_change_forces_source_without_rewriting_comfort(self):
        self.states[self.config['cv']]['state'] = 'heat'
        self.enable()
        self.states[self.config['cv']]['attributes']['temperature'] = 19.5
        self.observe(NOW+1)
        view = self.scheduler.view(NOW+1)
        self.assertTrue(view['overrides'][0]['forced_source'])
        self.assertEqual(view['overrides'][0]['status'],'observed')
        self.assertEqual(view['comfort']['zones']['beneden']['request']['target'],18)
        self.assertEqual(self.calls, [])

    def test_fixed_zone_manual_choice_survives_below_boundary_and_restart(self):
        entity=self.config['zones'][1]['device']
        self.states[entity]['state']='heat'
        self.enable()
        with patch('time.time', return_value=NOW+1):
            self.submit(self.payload('boven','temperature',19.5))
        self.observe(NOW+2)
        self.assertIsNone(self.scheduler.view(NOW+2)['overrides'][0]['until'])
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertEqual(other.schedule.view(NOW+86400)['overrides'][0]['source'],'boven')
        other.schedule.resume(NOW+86401)
        self.assertEqual(other.schedule.view(NOW+86401)['overrides'],[])
        self.assertEqual(len(self.calls),1)

    def test_own_delayed_feedback_does_not_extend_override(self):
        self.states[self.config['cv']]['state']='heat'
        self.apply=False
        self.enable()
        with patch('time.time', return_value=NOW+1):
            self.submit(self.payload('cv','temperature',19.5))
        original=copy.deepcopy(self.scheduler.view(NOW+1)['overrides'][0])
        self.observe(NOW+100)
        self.states[self.config['cv']]['attributes']['temperature']=19.5
        self.observe(NOW+200)
        hold=self.scheduler.view(NOW+200)['overrides'][0]
        self.assertEqual(hold['since'],original['since'])
        self.assertEqual(hold['until'],original['until'])
        self.assertEqual(hold['status'],'confirmed')

    def test_failed_command_is_not_a_confirmed_forced_source(self):
        self.states[self.config['cv']]['state']='heat'
        self.enable();self.status=400
        with patch('time.time', return_value=NOW+1):
            self.submit(self.payload('cv','temperature',19.5))
        hold=self.scheduler.view(NOW+1)['overrides'][0]
        self.assertFalse(hold['active']);self.assertFalse(hold['confirmed'])
        self.assertEqual(hold['status'],'failed')

    def test_mode_off_is_a_hold_not_forced_heating(self):
        self.states[self.config['cv']]['state']='heat'
        self.enable()
        self.states[self.config['cv']]['state']='off';self.observe(NOW+1)
        hold=self.scheduler.view(NOW+1)['overrides'][0]
        self.assertFalse(hold['forced_source'])
        self.assertEqual(hold['value'],'off')

    def test_legacy_migration_archives_settings_and_never_replays(self):
        legacy=dict(settings=dict(enabled=True,source='cv',entries=[dict(day=0,time='06:00',temperature=20)]),
                    revision=3,baseline={},override=None,action=dict(id='old-command'),fault=None,door=None)
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)',(json.dumps(legacy),))
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        migrated=other.schedule.view(NOW)
        self.assertFalse(migrated['settings']['enabled'])
        self.assertNotIn('source',migrated['settings'])
        self.assertTrue(migrated['migration'])
        settings=copy.deepcopy(migrated['settings']);settings['enabled']=True
        self.assertEqual(sum(w['ends_at']-w['starts_at'] for w in occurrences(settings,NOW)
                             if NOW <= w['starts_at'] < NOW+7*86400),7*86400)
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT payload FROM hc_schedule_archive').fetchone()[0]),legacy)
        again=Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertEqual(again.schedule.data['revision'],4)
        self.assertEqual(self.calls,[])

    def test_overlap_week_wrap_invalid_ranges_and_stale_revision(self):
        for windows in [[window(),window(start='19:00',end='23:00')],
                        [window(day=6,start='22:00',end='06:00'),window(day=0,start='05:00',end='07:00')],
                        [window(start='18:00',end='18:00')], [window(target=36)],
                        [window(target=float('nan'))], [window(day=True)], [window(start='24:00')]]:
            bad=dict(self.settings,windows=windows)
            with self.assertRaises(ValueError): validate_settings(bad)
        with self.assertRaises(ValueError):
            validate_settings(dict(self.settings,source='cv'))
        with self.assertRaises(ValueError):
            self.scheduler.update(dict(revision=99,settings=self.settings),NOW)

    def test_dst_duration_and_adjacent_boundaries(self):
        settings=dict(self.settings,windows=[window(day=5,start='22:00',end='06:00')])
        for date,hours in [(datetime(2026,3,28,23,tzinfo=TZ),7),(datetime(2026,10,24,23,tzinfo=TZ),9)]:
            now=date.timestamp()
            w=next(w for w in occurrences(settings,now) if w['starts_at'] <= now < w['ends_at'])
            self.assertEqual(w['ends_at']-w['starts_at'],hours*3600)
        settings['windows']=[window(day=6,start='00:00',end='02:30'),window(day=6,start='02:30',end='04:00')]
        now=datetime(2026,10,25,0,tzinfo=TZ).timestamp()
        windows=[w for w in occurrences(settings,now) if now <= w['starts_at'] < now+86400]
        self.assertEqual(windows[0]['ends_at'],windows[1]['starts_at'])

    def test_storage_failure_rolls_back_edit_and_blocks_manual_write(self):
        self.enable()
        before=copy.deepcopy(self.scheduler.data)
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_schedule BEFORE INSERT ON hc_schedule BEGIN SELECT RAISE(FAIL,'disk'); END")
        with self.assertRaises(sqlite3.Error):
            self.scheduler.update(dict(revision=1,settings=dict(self.settings,enabled=False)),NOW)
        self.assertEqual(self.scheduler.data,before)
        with self.assertRaises(sqlite3.Error): self.submit()
        self.assertEqual(self.calls,[])

    def test_api_csrf_ingress_and_no_service_on_save_or_resume(self):
        url=self.server(handler(self.runtime,False))
        raw=json.dumps(dict(revision=0,settings=self.settings)).encode()
        for path,body in [('/api/schedule',raw),('/api/resume',b'{}')]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url+path,data=body,headers={'Content-Type':'application/json'}))
            self.assertEqual(error.exception.code,403)
        headers={'Content-Type':'application/json','X-HC-CSRF':self.runtime.csrf_token}
        saved=json.load(urlopen(Request(url+'/api/schedule',data=raw,headers=headers)))
        self.assertTrue(saved['schedule']['settings']['enabled'])
        json.load(urlopen(Request(url+'/api/resume',data=b'{}',headers=headers)))
        self.assertEqual(self.calls,[])
        ingress=self.server(handler(self.runtime,True))
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(ingress+'/api/schedule',data=raw,headers=headers))
        self.assertEqual(error.exception.code,403)
