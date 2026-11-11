"""Automatic heating at the real HA HTTP, SQLite and runtime seams."""
import copy
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_control import ControlFixture
from picot_hc.__main__ import Runtime, handler
from picot_hc.schedule import DOOR

NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc).timestamp()


class HeatingTests(ControlFixture):
    def setUp(self):
        super().setUp()
        self.heat = self.runtime.heating
        self.config = self.runtime.config
        self.apply = True
        self.at = NOW
        for zone in self.config['zones']:
            zone.update(minimum=10, target=20, maximum=25)
            self.states[zone['temperature']] = dict(entity_id=zone['temperature'], state='18', attributes={'unit_of_measurement':'�C'},
                last_updated=datetime.fromtimestamp(NOW, timezone.utc).isoformat())
        self.runtime.schedule.data['settings'].update(setback_temperature=20, thermostat_temperature=20)
        self.runtime.schedule.save()
        self.states[DOOR] = dict(entity_id=DOOR, state='off', attributes={})
        self.price(.25)

    def price(self, value):
        self.states[self.config['price_entity']] = dict(entity_id=self.config['price_entity'], state=str(value), attributes={
            'unit_of_measurement':'EUR/kWh', 'raw_today':[dict(
                start=datetime.fromtimestamp(NOW-3600,timezone.utc).isoformat(),
                end=datetime.fromtimestamp(NOW+86400,timezone.utc).isoformat(), value=value)]})

    def temperature(self, zone, value):
        entity = next(z['temperature'] for z in self.config['zones'] if z['id'] == zone)
        self.states[entity]['state'] = str(value)

    def poll(self, at=None):
        self.at = self.at+31 if at is None else at
        with patch('time.time', return_value=self.at):
            self.ctl.observe(self.states, self.at, self.at)
            self.heat.tick(self.config, self.at)
            return self.heat.view(self.config, self.at)

    def enable(self):
        with patch('time.time', return_value=NOW):
            self.ctl.observe(self.states, NOW, NOW)
            self.heat.update(dict(revision=0, settings=dict(self.heat.data['settings'], enabled=True)))

    def test_missing_temperature_grace_holds_then_stops(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        self.temperature('beneden','unavailable')
        view=self.poll(NOW+180)
        self.assertEqual(len(self.calls),1)
        self.assertIn('beneden',view['data_grace_sources'])
        self.poll(NOW+479)
        self.assertEqual(len(self.calls),1)
        self.poll(NOW+480)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_data_recovery_during_grace_does_not_cycle_or_write_target(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        self.temperature('beneden','unavailable'); self.poll(NOW+180)
        self.runtime.schedule.data['settings']['thermostat_temperature']=21
        self.poll(NOW+240)
        self.assertEqual(len(self.calls),1)
        self.temperature('beneden',18)
        view=self.poll(NOW+270)
        self.assertEqual(view['data_grace_sources'],[])
        self.assertEqual(self.calls[-1][1],dict(entity_id=self.config['zones'][0]['device'],temperature=21,hvac_mode='heat'))
        self.assertFalse(any(c[1].get('hvac_mode')=='off' for c in self.calls))

    def test_missing_door_grace_and_explicit_disable(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        self.states[DOOR]['state']='unavailable'
        view=self.poll(NOW+180)
        self.assertIn('beneden',view['data_grace_sources'])
        self.assertEqual(len(self.calls),1)
        self.heat.update(dict(revision=self.heat.data['revision'],settings=dict(self.heat.data['settings'],enabled=False)))
        self.poll(NOW+210)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_restart_preserves_enabled_and_confirmed_heat_without_replay(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertTrue(other.heating.data['settings']['enabled'])
        self.assertTrue(other.heating.armed)
        with patch('time.time',return_value=NOW+200):
            other.heating.tick(other.config,NOW+200)
            other.control.observe(self.states,NOW+200,NOW+200)
            other.heating.tick(other.config,NOW+200)
        self.assertEqual(len(self.calls),1)

    def test_grace_deadline_survives_hc_restart(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        self.temperature('beneden','unavailable'); self.poll(NOW+180)
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.heat,self.ctl=other.heating,other.control
        self.poll(NOW+450)
        self.assertEqual(len(self.calls),1)
        self.poll(NOW+480)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_missing_temperature_does_not_authorize_airco_start(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.temperature('beneden','unavailable'); self.enable()
        view=self.poll(NOW+121)
        self.assertEqual(view['data_grace_sources'],[])
        self.assertEqual(self.calls,[])

    def test_temporary_missing_price_holds_existing_airco(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(NOW+152)
        del self.states[self.config['price_entity']]
        view=self.poll(NOW+180)
        self.assertIn('beneden',view['data_grace_sources'])
        self.assertEqual(len(self.calls),1)
        self.price(.25); view=self.poll(NOW+240)
        self.assertEqual(view['data_grace_sources'],[])
        self.assertEqual(len(self.calls),1)
        del self.states[self.config['price_entity']]
        self.poll(NOW+270); self.poll(NOW+570)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_four_sources_and_shared_cv_switch_waits_for_off_feedback(self):
        self.enable()
        self.poll(NOW+121); self.poll(); self.poll(); self.poll()
        self.assertEqual({c[1]['entity_id'] for c in self.calls}, {z['device'] for z in self.config['zones'] if not z.get('monitor_only')})
        self.assertTrue(all(c['status']=='confirmed' for c in self.ctl.records()))
        self.assertEqual(self.runtime.schedule.view(self.at)['overrides'], [])
        self.price(.90)
        self.apply = False
        self.poll(NOW+500)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')
        self.poll(); self.poll()
        self.assertFalse(any(c[1]['entity_id']==self.config['cv'] for c in self.calls))
        # Both old AC stops must independently confirm before CV can start.
        for z in self.config['zones'][:2]: self.states[z['device']]['state']='off'
        self.apply = True
        self.poll()
        self.assertEqual(self.calls[-1][1], {'entity_id':self.config['cv'],'hvac_mode':'heat'})
        self.poll()
        self.assertEqual(self.states[self.config['cv']]['attributes']['temperature'],20)
        self.assertEqual(self.runtime.schedule.view(self.at)['overrides'], [])

    def test_cv_uses_downstairs_target_and_cannot_heat_upstairs_alone(self):
        self.config['zones'][1]['target']=18
        self.temperature('boven',16)
        self.temperature('badkamer',22)
        self.price(.90); self.enable(); self.poll(NOW+121)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'heat')
        self.assertEqual(self.calls[-1][1]['entity_id'],self.config['cv'])
        self.poll()
        self.assertEqual(self.states[self.config['cv']]['attributes']['temperature'],20)
        self.temperature('beneden',20)
        self.poll(); self.poll(); self.poll()
        self.assertEqual(self.heat.view(self.config,self.at)['desired'], {'cv':20})
        # A fresh situation with demand upstairs alone must never select CV.
        self.heat.data['owned'].clear()
        self.states[self.config['cv']]['state']='off'
        self.ctl.states[self.config['cv']]['state']='off'
        self.assertNotIn('cv',self.heat.plan(self.config,self.at)['desired'])

    def cv_ready(self):
        self.states[self.config['cv']]['attributes'].update(min_temp=5, current_temperature=20, hvac_action='idle')
        self.temperature('boven',22); self.temperature('badkamer',22)

    def test_cv_ends_at_15_and_can_be_selected_again(self):
        self.cv_ready(); self.price(.90); self.enable()
        self.poll(NOW+121); self.poll()
        self.heat.update(dict(revision=1, settings=dict(self.heat.data['settings'], enabled=False)))
        self.poll(); self.poll(); self.poll()
        self.assertEqual(self.calls[-1][1], dict(entity_id=self.config['cv'], temperature=15, hvac_mode='heat'))
        self.assertEqual(len(self.calls),2)
        self.heat.update(dict(revision=2, settings=dict(self.heat.data['settings'], enabled=True)))
        self.poll()
        self.assertEqual(len(self.calls),2)
        self.poll(self.at+181)
        self.assertEqual(self.calls[-1][1]['temperature'],20)
        self.assertFalse(any(c[1].get('hvac_mode')=='off' for c in self.calls))

    def test_cv_standby_waits_for_idle_before_airco_takeover(self):
        self.cv_ready(); self.price(.90); self.enable()
        self.poll(NOW+121); self.poll()
        self.states[self.config['cv']]['attributes']['hvac_action']='heating'
        self.price(.25); self.poll(NOW+500); self.poll(); self.poll()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.calls[-1][1], dict(entity_id=self.config['cv'], temperature=15, hvac_mode='heat'))
        self.states[self.config['cv']]['attributes']['hvac_action']='idle'
        self.poll()
        self.assertEqual(self.calls[-1][1]['entity_id'],self.config['zones'][0]['device'])

    def test_cv_failed_standby_is_not_replayed_after_restart(self):
        self.cv_ready(); self.price(.90); self.enable()
        self.poll(NOW+121); self.poll()
        self.price(.25); self.apply=False
        self.poll(NOW+500); self.poll(NOW+850)
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.heat,self.ctl=other.heating,other.control
        self.poll(NOW+880); self.poll(NOW+900)
        self.assertEqual(len(self.calls),2)
        self.assertIn('cv',self.heat.data['faults'])
        self.assertEqual(self.calls[-1][1].get('temperature'),15)

    def test_manual_cv_expires_at_schedule_boundary_across_restart(self):
        self.cv_ready()
        self.runtime.schedule.data['settings'].update(enabled=True, setback_temperature=17, windows=[dict(
            day=2, start='13:00', end='14:05', target=20, hard=False)])
        self.runtime.schedule.save()
        self.enable(); self.poll(NOW+121); self.poll()
        self.states[self.config['cv']]['state']='heat'
        self.states[self.config['cv']]['attributes']['temperature']=23
        self.poll(NOW+180); self.poll()
        hold=self.runtime.schedule.view(self.at)['overrides'][0]
        self.assertEqual(hold['until'],NOW+300)
        count=len(self.calls)
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.heat,self.ctl=other.heating,other.control
        self.poll(NOW+299)
        self.assertEqual(len(self.calls),count)
        self.poll(NOW+300)
        self.assertEqual(self.calls[-1][1],dict(entity_id=self.config['cv'], temperature=15, hvac_mode='heat'))
        self.assertEqual(other.schedule.view(self.at)['overrides'],[])

    def test_cv_choice_accepts_satisfied_upstairs(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.price(.90); self.enable(); self.poll(NOW+121)
        self.assertEqual(self.calls[-1][1]['entity_id'],self.config['cv'])

    def test_deadband_then_maintaining_and_minimum_off_time(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.temperature('beneden',19.8); self.enable(); self.poll(NOW+121)
        self.assertEqual(self.calls,[])
        self.temperature('beneden',19.6); self.poll()
        self.assertEqual(len(self.calls),1)
        self.temperature('beneden',19.9); self.poll()
        self.assertEqual(len(self.calls),1)
        self.temperature('beneden',20); self.poll()
        self.assertEqual(len(self.calls),1)
        # Protective stop still enforces minimum off time before restarting.
        self.temperature('beneden','unavailable'); self.poll()
        self.poll(self.at+300)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')
        self.temperature('beneden',19); self.poll()
        self.assertEqual(len(self.calls),2)
        self.poll(self.at+180)
        self.assertEqual(len(self.calls),3)

    def test_door_preempts_pending_heat_despite_missing_temperature(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.apply=False; self.enable(); self.poll(NOW+121)
        self.states[DOOR]['state']='on'; self.poll()
        self.assertEqual(len(self.calls),1)
        self.temperature('beneden','unavailable'); self.poll(NOW+220)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')
        self.assertIn('superseded',[c['status'] for c in self.ctl.records()])

    def test_unknown_door_blocks_start_then_closed_recovery_delay(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.config['gas_valid_until']='2020-01-01'  # Isolate the airco door guard; upstairs no longer blocks CV.
        self.states[DOOR]['state']='unknown'; self.enable(); self.poll(NOW+121)
        self.assertEqual(self.calls,[])
        self.states[DOOR]['state']='off'; self.poll()
        self.assertEqual(self.calls,[])
        self.poll(NOW+273)
        self.assertEqual(len(self.calls),1)

    def test_manual_cv_hold_stops_owned_aircos_and_never_changes_cv(self):
        self.temperature('badkamer',22); self.enable()
        self.poll(NOW+121); self.poll(); self.poll()
        self.states[self.config['cv']]['state']='heat'
        self.states[self.config['cv']]['attributes']['temperature']=21
        self.poll(); self.poll(); self.poll()
        self.assertEqual(len(self.calls),4)
        self.assertTrue(all(c[1]['entity_id']!=self.config['cv'] for c in self.calls))
        self.assertEqual(self.states[self.config['cv']]['attributes']['temperature'],21)

    def test_manual_race_after_planning_blocks_automatic_command(self):
        self.enable()
        self.temperature('boven',22); self.temperature('badkamer',22)
        from picot_hc.core import fetch_states
        def racing_read(*args):
            self.states[self.config['cv']]['state']='heat'
            return fetch_states(*args)
        with patch('picot_hc.control.fetch_states', side_effect=racing_read):
            self.poll(NOW+121)
        self.assertEqual(self.calls,[])

    def test_manual_takeover_is_not_stopped(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll()
        self.states[self.config['zones'][0]['device']]['attributes']['temperature']=23
        self.poll(); self.states[DOOR]['state']='on'; self.poll(NOW+300); self.poll(NOW+400)
        self.assertEqual(len(self.calls),1)

    def test_stale_measurement_stops_owned_and_freshness_is_not_poll_time(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll(); self.poll(NOW+901)
        self.assertEqual(len(self.calls),1)
        self.poll(NOW+1201)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')
        self.poll(NOW+1300)
        self.assertEqual(len(self.calls),2)

    def test_invalid_price_and_expired_gas(self):
        self.enable(); del self.states[self.config['price_entity']]
        self.poll(NOW+121)
        self.assertEqual(self.calls,[])
        self.price(.90); self.config['gas_valid_until']='2020-01-01'
        view=self.poll()
        self.assertIsNone(view['costs']['cv'])
        self.assertNotIn('cv',view['desired'])

    def test_costs_use_consistent_higher_heating_value_and_negative_prices(self):
        self.enable(); view=self.poll(NOW+121)
        self.assertAlmostEqual(view['costs']['cv'],1.41197/(35.17/3.6*.9))
        self.assertAlmostEqual(view['costs']['boven'],.25/3)
        self.price(-.1); view=self.poll()
        self.assertNotIn('cv',view['desired'])
        self.temperature('beneden',22); self.temperature('boven',22); self.temperature('badkamer',22)
        self.assertEqual(self.poll()['desired'],{'beneden':20})

    def test_timeout_stop_once_and_confirmed_stop_clears_fault(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.apply=False; self.enable(); self.poll(NOW+121)
        self.poll(NOW+450); self.poll(NOW+800); self.poll(NOW+900)
        self.assertEqual(len(self.calls),2)  # One start, one protective stop.
        self.assertNotIn('beneden',self.heat.data['faults'])
        self.assertEqual(self.heat.data['fault_recoveries']['beneden']['reason'],'latest_intent_confirmed')

    def test_restart_confirms_arrived_start_without_stopping_it(self):
        self.enable(); self.poll(NOW+121)
        other=Runtime(self.config,self.store,self.url,'fake-secret')
        self.assertTrue(other.heating.data['settings']['enabled'])
        with patch('time.time',return_value=NOW+200):
            other.control.observe(self.states,NOW+200,NOW+200)
            other.heating.tick(other.config,NOW+200)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.calls[-1][1]['entity_id'],self.config['zones'][1]['device'])
        self.assertTrue(all(c[1]['hvac_mode']=='heat' for c in self.calls))

    def test_disable_stops_only_owned_sources(self):
        self.temperature('boven',22); self.temperature('badkamer',22)
        self.enable(); self.poll(NOW+121); self.poll()
        self.heat.update(dict(revision=1,settings=dict(self.heat.data['settings'],enabled=False)))
        self.poll(); self.poll()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_storage_failure_cannot_send_and_edit_rolls_back(self):
        self.enable()
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER deny_heating BEFORE INSERT ON hc_heating BEGIN SELECT RAISE(FAIL,'disk'); END")
        before=copy.deepcopy(self.heat.data)
        with self.assertRaises(sqlite3.Error):
            self.heat.update(dict(revision=1, settings=dict(self.heat.data['settings'],enabled=False)))
        self.assertEqual(before,self.heat.data)
        with self.assertRaises(sqlite3.Error):self.poll(NOW+121)
        self.assertEqual(self.calls,[])

    def test_api_csrf_validation_and_save_does_not_dispatch(self):
        url=self.server(handler(self.runtime,False))
        payload=dict(revision=0,settings=dict(self.heat.data['settings'],enabled=True))
        raw=json.dumps(payload).encode()
        with self.assertRaises(HTTPError) as err:
            urlopen(Request(url+'/api/heating',data=raw,headers={'Content-Type':'application/json'}))
        self.assertEqual(err.exception.code,403)
        headers={'Content-Type':'application/json','X-HC-CSRF':self.runtime.csrf_token}
        result=json.load(urlopen(Request(url+'/api/heating',data=raw,headers=headers)))
        self.assertTrue(result['heating']['enabled'])
        self.assertEqual(self.calls,[])
        for bad in [float('nan'),True,0,2]:
            payload['revision']=1;payload['settings']['cv_efficiency']=bad
            with self.assertRaises(HTTPError):
                urlopen(Request(url+'/api/heating',data=json.dumps(payload).encode(),headers=headers))

    def test_resume_releases_manual_cv_and_switches_back_to_airco(self):
        self.cv_ready()
        self.temperature('boven',18)
        self.temperature('badkamer',22);self.enable()
        self.states[self.config['cv']]['state']='heat'
        self.poll(NOW+121)
        self.assertEqual(self.calls,[])
        self.runtime.schedule.resume(self.at)
        self.poll()
        self.assertEqual(self.calls[-1][1],{'entity_id':self.config['cv'],'hvac_mode':'heat','temperature':15})
        self.poll();self.poll()
        self.assertEqual({c[1]['entity_id'] for c in self.calls[1:]},
                         {z['device'] for z in self.config['zones'][:2]})

    def test_failed_stop_requires_explicit_release(self):
        self.temperature('boven',22);self.temperature('badkamer',22)
        self.enable();self.poll(NOW+121);self.poll()
        self.temperature('beneden','unavailable')
        self.poll()
        self.status=400;self.apply=False
        self.poll(self.at+300);self.poll();self.poll()
        self.assertEqual(len(self.calls),2)
        self.heat.reset_faults();self.status=200;self.apply=True
        self.poll();self.poll()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')

    def test_unavailable_aircos_allow_eligible_cv(self):
        self.temperature('badkamer',22)
        for zone in self.config['zones'][:2]:self.states[zone['device']]['state']='unavailable'
        self.enable();self.poll(NOW+121)
        self.assertEqual(self.calls[-1][1]['entity_id'],self.config['cv'])

    def test_schedule_window_changes_target_without_binding_source(self):
        settings=copy.deepcopy(self.runtime.schedule.data['settings'])
        settings.update(enabled=True, windows=[dict(day=2,start='14:00',end='15:00',target=21,hard=True)])
        self.runtime.schedule.update(dict(revision=0,settings=settings),NOW)
        self.enable();view=self.poll(NOW+121)
        self.assertEqual(view['zones']['beneden']['target'],21)
        self.assertEqual(self.calls[-1][1]['temperature'],21)

    def test_real_collector_dispatches_and_persists_measurements(self):
        self.enable()
        self.runtime.weather.entity=''
        with patch('time.time',return_value=NOW+121):self.runtime.collect()
        self.assertEqual(self.runtime.connection,'connected')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.store.latest()['zones'][0]['samples']['temperature']['value'],18)

    def timer(self, minutes=5, temperature=22):
        self.ctl.observe(self.states, NOW, NOW)
        self.heat.update_timer(dict(revision=self.heat.data['timer_revision'], action='start',
                                   minutes=minutes, temperature=temperature), self.config, NOW)

    def test_timer_only_bathroom_without_global_enable_or_tariff_and_expires(self):
        self.states.pop(self.config['price_entity'])
        self.timer(minutes=1)
        self.assertEqual(self.calls, [])
        view=self.poll(NOW+1)
        self.assertTrue(view['timer']['active'])
        self.assertEqual(view['zones']['badkamer']['target'],22)
        self.assertEqual(self.calls[-1],('/api/services/switch/turn_on',{'entity_id':self.config['zones'][2]['device']}))
        self.poll(NOW+31);view=self.poll(NOW+60)
        self.assertFalse(view['timer']['active'])
        self.assertEqual(self.calls[-1][0],'/api/services/switch/turn_off')
        self.poll();self.assertEqual(len(self.calls),2)

    def test_timer_temperature_feedback_and_stale_measurement(self):
        self.timer();self.poll(NOW+1);self.poll()
        self.temperature('badkamer',22);self.poll()
        self.assertEqual(self.calls[-1][0],'/api/services/switch/turn_off')
        self.poll();self.temperature('badkamer',18)
        self.poll(NOW+280)
        self.assertEqual(self.calls[-1][0],'/api/services/switch/turn_on')
        entity=self.config['zones'][2]['temperature']
        self.states[entity]['state']='unavailable';self.poll(NOW+290)
        self.assertEqual(self.calls[-1][0],'/api/services/switch/turn_off')

    def test_timer_stop_returns_fixed_goal_and_global_off_cancels(self):
        self.enable();self.timer();view=self.poll(NOW+1)
        self.heat.update_timer(dict(revision=1,action='stop'),self.config,NOW+2)
        view=self.heat.view(self.config,NOW+2)
        self.assertEqual(view['zones']['badkamer']['target'],20)
        self.assertFalse(view['timer']['active'])
        self.timer()
        self.heat.update(dict(revision=self.heat.data['revision'],settings=dict(self.heat.data['settings'],enabled=False)))
        self.assertFalse(self.heat.timer_active(NOW+3))

    def test_timer_restart_cancels_and_stops_owned_bathroom_without_restart(self):
        from picot_hc.heating import Heating
        self.timer();self.poll(NOW+1);self.poll()
        self.heat=Heating(self.ctl,self.runtime.schedule,self.store)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.heat.data['timer']['status'],'restart')
        self.poll();self.poll();self.poll()
        self.assertEqual([c[0] for c in self.calls],['/api/services/switch/turn_on','/api/services/switch/turn_off'])

    def test_timer_manual_off_cancels_and_resume_does_not_restart_timer(self):
        self.timer();self.poll(NOW+1);self.poll()
        self.states[self.config['zones'][2]['device']]['state']='off'
        view=self.poll()
        self.assertEqual(view['timer']['status'],'manual')
        self.runtime.schedule.resume(self.at)
        self.poll();self.assertEqual(len(self.calls),1)

    def test_timer_validation_revision_and_storage_failure(self):
        for minutes,target in [(0,22),(181,22),(True,22),(1.5,22),(5,26),(5,float('nan')),(5,True)]:
            with self.assertRaises(ValueError):self.timer(minutes,target)
        self.timer()
        with self.assertRaises(ValueError):
            self.heat.update_timer(dict(revision=0,action='start',minutes=5,temperature=22),self.config,NOW+1)
        before=copy.deepcopy(self.heat.data)
        with patch.object(self.heat,'save',side_effect=sqlite3.Error('full')):
            with self.assertRaises(sqlite3.Error):
                self.heat.update_timer(dict(revision=1,action='stop'),self.config,NOW+1)
        self.assertEqual(self.heat.data,before)
        self.assertEqual(self.calls,[])

    def test_timer_expiry_preempts_unconfirmed_start(self):
        self.apply=False;self.timer(minutes=1);self.poll(NOW+1)
        self.poll(NOW+60)
        self.assertEqual([c[0] for c in self.calls],['/api/services/switch/turn_on','/api/services/switch/turn_off'])

    def test_timer_api_requires_csrf_and_returns_remaining_time(self):
        url=self.server(handler(self.runtime,False))
        raw=json.dumps(dict(revision=0,action='start',minutes=30,temperature=22)).encode()
        with self.assertRaises(HTTPError) as err:
            urlopen(Request(url+'/api/heating/timer',data=raw,headers={'Content-Type':'application/json'}))
        self.assertEqual(err.exception.code,403)
        headers={'Content-Type':'application/json','X-HC-CSRF':self.runtime.csrf_token}
        result=json.load(urlopen(Request(url+'/api/heating/timer',data=raw,headers=headers)))
        self.assertTrue(result['heating']['timer']['active'])
        self.assertGreater(result['heating']['timer']['remaining_seconds'],1790)
        self.assertEqual(self.calls,[])

    def test_timer_restart_cleanup_does_not_stop_other_owned_sources(self):
        from picot_hc.heating import Heating
        self.enable();self.timer();self.poll(NOW+121);self.poll();self.poll();self.poll()
        self.assertEqual(len(self.calls),3)
        self.heat=Heating(self.ctl,self.runtime.schedule,self.store)
        self.poll();self.poll()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.heat.data['timer']['status'],'restart')
        self.assertTrue(self.heat.data['settings']['enabled'])
        self.assertEqual(self.states[self.config['zones'][0]['device']]['state'],'heat')

    def test_removed_bounds_during_timer_stop_owned_heat(self):
        self.timer();self.poll(NOW+1);self.poll()
        self.config['zones'][2]['maximum']=None
        self.poll()
        self.assertEqual(self.calls[-1][0],'/api/services/switch/turn_off')

    def live_reports(self, age=0, value='18'):
        self.template_reports=[]
        for zone in self.config['zones']:
            entity=zone['temperature']
            self.states[entity]['last_updated']=datetime.fromtimestamp(NOW-3600,timezone.utc).isoformat()
            self.template_reports.append(dict(self.states[entity],state=value,
                last_reported=datetime.fromtimestamp(NOW+121-age,timezone.utc).isoformat()))
        self.runtime.weather.entity=''

    def collect_at(self, moment=NOW+121):
        with patch('time.time',return_value=moment):
            self.runtime.collect()
            return self.heat.view(self.config,moment)

    def test_live_report_accepts_unchanged_temperature_and_exports_actual_time(self):
        self.enable();self.live_reports();view=self.collect_at()
        self.assertEqual(self.runtime.connection,'connected')
        self.assertTrue(view['zones']['beneden']['demand'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.template_calls),2)  # Poll and fresh-read guard.
        sample=self.store.latest()['zones'][1]['samples']['temperature']
        self.assertEqual(sample['source_reported'],self.template_reports[1]['last_reported'])
        self.assertNotEqual(sample['source_reported'],sample['source_updated'])

    def test_live_report_uses_matching_value_not_old_rest_value(self):
        self.enable();self.live_reports(value='22');view=self.collect_at()
        self.assertEqual(view['zones']['beneden']['temperature'],22)
        self.assertFalse(view['zones']['beneden']['demand'])
        self.assertEqual(self.calls,[])

    def test_live_report_old_future_missing_and_invalid_block_starts(self):
        self.enable()
        for age in [3600,-60]:
            self.live_reports(age=age);view=self.collect_at()
            self.assertFalse(view['zones']['beneden']['demand'])
        for reports in [[],{},[{'entity_id':'sensor.other'}]]:
            self.template_reports=reports;view=self.collect_at()
            self.assertIn('ontvangsttijd',view['zones']['beneden']['reason'])
        self.assertEqual(self.calls,[])

    def test_template_failure_waits_before_stopping_owned_heat(self):
        self.enable();self.live_reports();self.collect_at()
        self.template_status=503
        view=self.collect_at(NOW+152)
        self.assertEqual(self.runtime.connection,'connected')
        self.assertIn('tijdelijk',view['zones']['beneden']['reason'])
        self.assertEqual(len(self.calls),1)
        self.collect_at(NOW+452)
        self.assertEqual(self.calls[-1][1]['hvac_mode'],'off')
        self.assertEqual(len(self.calls),2)

    def test_live_stale_report_also_blocks_bathroom_timer(self):
        self.timer();self.live_reports(age=3600);view=self.collect_at()
        self.assertTrue(view['timer']['active'])
        self.assertFalse(view['zones']['badkamer']['demand'])
        self.assertEqual(self.calls,[])
