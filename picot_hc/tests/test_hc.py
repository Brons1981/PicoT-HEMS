import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from picot_hc.core import Store, snapshot, validate, prices, fetch_states, observation, tariff_confirmed, battery_observation
from picot_hc.__main__ import Runtime, handler

ROOT = Path(__file__).resolve().parents[1]
NOW = 1789293600.0

class HC(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/'options.example.json').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def state(self, state, unit=None):
        return dict(state=state, attributes={'unit_of_measurement':unit}, last_updated='2026-09-13T10:00:00Z')

    def test_missing_sensors_do_not_become_zero(self):
        d=snapshot(self.config, {}, NOW)
        self.assertEqual(len(d['zones']),3)
        self.assertIsNone(d['zones'][0]['samples']['temperature']['value'])
        self.assertEqual(d['presence']['quality'],'missing')
        self.assertNotEqual(d['presence']['value'],'not_home')

    def test_numeric_validation_and_zero(self):
        for bad in ['unavailable','unknown','NaN','inf','garbage']:
            self.assertIsNone(observation('sensor.x',{'sensor.x':self.state(bad,'W')},NOW,True,'W')['value'])
        self.assertEqual(observation('sensor.x',{'sensor.x':self.state('0','W')},NOW,True,'W')['value'],0)
        self.assertEqual(observation('sensor.x',{'sensor.x':self.state('23','°F')},NOW,True,'°C')['quality'],'unit_mismatch')

    def test_bounds_reject_invalid_order(self):
        validate(self.config)
        self.config['zones'][0].update(minimum=22,target=19)
        with self.assertRaises(ValueError):validate(self.config)

    def test_prices_explicit_quarters_negative_unit_conversion_and_gaps(self):
        self.config['confirmed_price_entity'] = ''
        s=self.state('10','EUR/MWh')
        s['attributes']['raw_today']=[{'start':'2026-09-13T10:00:00+02:00','end':'2026-09-13T10:15:00+02:00','value':-20},{'start':'2026-09-13T10:30:00+02:00','end':'2026-09-13T10:45:00+02:00','value':150}]
        rows,warnings=prices(s,self.config,NOW)
        self.assertEqual([x['value'] for x in rows],[-.02,.15])
        self.assertEqual(rows[1]['start']-rows[0]['end'],900)
        self.assertTrue(warnings) # unconfirmed tariff basis is explicit

    def test_prices_fail_closed_on_ambiguous_time_or_overlap(self):
        s=self.state('1','EUR/kWh')
        s['attributes']['raw_today']=[{'start':'2026-09-13T10:00:00','end':'2026-09-13T10:15:00','value':1}]
        self.assertEqual(prices(s,self.config,NOW)[0],[])
        s['attributes']['raw_today']=[{'start':'2026-09-13T10:00:00Z','end':'2026-09-13T11:00:00Z','value':1},{'start':'2026-09-13T10:30:00Z','end':'2026-09-13T11:00:00Z','value':2}]
        self.assertEqual(prices(s,self.config,NOW)[0],[])

    def test_sqlite_restart_and_retention(self):
        path=Path(self.tmp.name)/'hc.sqlite3'; store=Store(path)
        store.save(snapshot(self.config,{},NOW-100*86400),90)
        store.save(snapshot(self.config,{},NOW),90)
        reopened=Store(path)
        self.assertEqual(reopened.latest()['collected'],NOW)
        self.assertEqual(len(reopened.history(0)),1)

    def server(self, cls):
        server=ThreadingHTTPServer(('127.0.0.1',0),cls)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_real_http_ingestion_persistence_dashboard_and_no_writes(self):
        calls=[]
        class FakeHA(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append((self.command,self.path,self.headers.get('Authorization')))
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps([{'entity_id':'sensor.temp','state':'21.5','attributes':{'unit_of_measurement':'°C'}}]).encode())
        url=self.server(FakeHA)
        self.config['zones'][0]['temperature']='sensor.temp'
        rt=Runtime(self.config,Store(Path(self.tmp.name)/'hc.sqlite3'),url+'/api','test-secret')
        rt.collect()
        self.assertEqual(rt.current()['zones'][0]['samples']['temperature']['value'],21.5)
        self.assertEqual(calls,[('GET','/api/states','Bearer test-secret')])
        dashboard=self.server(handler(rt,False))
        body=urlopen(dashboard+'/api/snapshot').read()
        self.assertNotIn(b'test-secret',body)
        self.assertEqual(json.loads(body)['mode'],'observe')
        self.assertIn(b'Home Climate',urlopen(dashboard+'/').read())
        self.assertEqual(len(json.load(urlopen(dashboard+'/api/history'))),1)
        with self.assertRaises(HTTPError) as cm:urlopen(Request(dashboard+'/api/snapshot',data=b'{}'))
        self.assertEqual(cm.exception.code,404)

    def test_ingress_rejects_direct_request(self):
        rt=Runtime(self.config,Store(Path(self.tmp.name)/'hc.sqlite3'),'','')
        url=self.server(handler(rt,True))
        with self.assertRaises(HTTPError) as cm:urlopen(url+'/')
        self.assertEqual(cm.exception.code,403)

    def test_ha_redirect_does_not_forward_token(self):
        requests=[]
        class Destination(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(self.headers.get('Authorization'))
                self.send_response(200);self.end_headers();self.wfile.write(b'[]')
        dest=self.server(Destination)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(302);self.send_header('Location',dest+'/states');self.end_headers()
        source=self.server(Redirect)
        with self.assertRaises(HTTPError):fetch_states(source,'test-secret')
        self.assertEqual(requests,[])

    def test_connection_failure_preserves_history_marks_stale(self):
        store=Store(Path(self.tmp.name)/'hc.sqlite3')
        store.save(snapshot(self.config,{},time.time()-3600),90)
        rt=Runtime(self.config,store,'http://127.0.0.1:1/api','')
        rt.collect()
        self.assertEqual(rt.current()['connection'],'disconnected')
        self.assertTrue(rt.current()['stale'])
        self.assertIsNotNone(rt.current()['collected'])

    def test_supervisor_options_optional_temperatures(self):
        c=json.loads((ROOT/'config.json').read_text())['options']
        validate(c)
        self.assertEqual(len(snapshot(c,{},NOW)['zones']),3)


    def settings_runtime(self):
        store = Store(Path(self.tmp.name) / 'hc.sqlite3')
        store.save(snapshot(self.config, {}, NOW), 90)
        runtime = Runtime(self.config, store, '', '')
        return runtime, self.server(handler(runtime, False))

    def post_settings(self, url, runtime, values, zone='beneden', token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-HC-CSRF'] = runtime.csrf_token
        return urlopen(Request(url + '/api/settings',
            data=json.dumps({'zone_id': zone, 'values': values}).encode(), headers=headers))

    def test_dashboard_settings_persist_without_ha_or_new_measurement(self):
        rt, url = self.settings_runtime()
        values = dict(minimum=16, target=19.5, maximum=22)
        result = json.load(self.post_settings(url, rt, values))
        self.assertEqual(result['settings']['target'], 19.5)
        current = json.load(urlopen(url + '/api/snapshot'))
        self.assertEqual(current['zones'][0]['settings']['target'], 19.5)
        self.assertEqual(current['collected'], NOW)
        self.assertEqual(current['settings_revision'], 1)
        reopened = Runtime(self.config, Store(rt.store.path), '', '')
        self.assertEqual(reopened.current()['zones'][0]['settings']['target'], 19.5)
        self.assertEqual(reopened.config['zones'][1], self.config['zones'][1])
        self.assertNotEqual(self.config['zones'][0].get('target'), 19.5)

    def test_settings_invalid_requests_do_not_change_saved_values(self):
        rt, url = self.settings_runtime()
        valid = dict(minimum=16, target=20, maximum=23)
        self.post_settings(url, rt, valid).close()
        for values in [dict(minimum=22, target=20, maximum=23),
                       dict(minimum=None, target=True, maximum=None),
                       dict(minimum=None, target=float('nan'), maximum=None),
                       dict(minimum=None, target='21', maximum=None),
                       dict(target=20), dict(valid, device='switch.other')]:
            with self.subTest(values=values), self.assertRaises(HTTPError) as cm:
                self.post_settings(url, rt, values)
            self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(HTTPError) as cm:
            self.post_settings(url, rt, valid, zone='unknown')
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(rt.store.settings()['beneden'], valid)

    def test_settings_clear_values_and_preserve_other_zones(self):
        rt, url = self.settings_runtime()
        self.post_settings(url, rt, dict(minimum=15, target=18, maximum=22), zone='boven').close()
        empty = dict(minimum=None, target=None, maximum=None)
        self.post_settings(url, rt, empty).close()
        reopened = Runtime(self.config, Store(rt.store.path), '', '')
        self.assertIsNone(reopened.config['zones'][0]['target'])
        self.assertEqual(reopened.config['zones'][1]['target'], 18)

    def test_settings_require_csrf_and_ingress(self):
        rt, url = self.settings_runtime()
        values = dict(minimum=16, target=20, maximum=23)
        with self.assertRaises(HTTPError) as cm:
            self.post_settings(url, rt, values, token=False)
        self.assertEqual(cm.exception.code, 403)
        ingress = self.server(handler(rt, True))
        with self.assertRaises(HTTPError) as cm:
            self.post_settings(ingress, rt, values)
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(rt.store.settings(), {})

    def test_settings_storage_failure_leaves_memory_and_database_unchanged(self):
        rt, url = self.settings_runtime()
        before = copy.deepcopy(rt.config)
        with rt.store.connect() as db:
            db.execute("CREATE TRIGGER block_settings BEFORE INSERT ON zone_settings BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        with self.assertRaises(HTTPError) as cm:
            self.post_settings(url, rt, dict(minimum=16, target=20, maximum=23))
        self.assertEqual(cm.exception.code, 503)
        self.assertEqual(rt.config, before)
        self.assertEqual(rt.store.settings(), {})

    def test_price_confirmation_is_source_bound_and_migrates_old_options(self):
        self.config.pop('confirmed_price_entity', None)
        self.config['price_basis_confirmed'] = False
        self.assertTrue(tariff_confirmed(self.config))
        self.assertTrue(snapshot(self.config, {}, NOW)['price_basis_confirmed'])
        self.config['price_entity'] = 'sensor.other_tariff'
        self.assertFalse(tariff_confirmed(self.config))
        self.config['price_basis_confirmed'] = True
        self.assertTrue(tariff_confirmed(self.config))

    def test_upstairs_meters_fill_old_blanks_and_preserve_custom_binding(self):
        zone = self.config['zones'][1]
        zone.update(power='', energy='')
        rt = Runtime(self.config, Store(Path(self.tmp.name) / 'hc.sqlite3'), '', '')
        effective = rt.config['zones'][1]
        self.assertEqual(effective['power'], 'sensor.shellyplugsg3_d0cf13c907e0_vermogen')
        self.assertEqual(effective['energy'], 'sensor.shellyplugsg3_d0cf13c907e0_energie')
        states = {effective['power']: self.state('350', 'W'),
                  effective['energy']: self.state('12.34', 'kWh')}
        samples = snapshot(rt.config, states, NOW)['zones'][1]['samples']
        self.assertEqual(samples['power']['value'], 350)
        self.assertEqual(samples['energy']['value'], 12.34)
        zone['power'] = 'sensor.custom_power'
        rt = Runtime(self.config, rt.store, '', '')
        self.assertEqual(rt.config['zones'][1]['power'], 'sensor.custom_power')
        zone.update(device='climate.other', power='', energy='')
        rt = Runtime(self.config, rt.store, '', '')
        self.assertEqual(rt.config['zones'][1]['power'], '')

    def test_ecowitt_upgrade_ingestion_and_persistence(self):
        expected = copy.deepcopy(self.config)
        self.config['outdoor'] = ''
        self.config.pop('outdoor_humidity')
        for zone in self.config['zones']:
            zone.update(temperature='', humidity='')
        self.config['zones'][2]['energy'] = ''
        states = []
        for zone in expected['zones']:
            for key, unit, value in [('temperature','°C','21.5'),('humidity','%','52'),('dewpoint','°C','11.2')]:
                states.append(dict(entity_id=zone[key], **self.state(value,unit)))
        for key, unit, value in [('outdoor','°C','12.5'),('outdoor_humidity','%','81'),('outdoor_dewpoint','°C','9.3')]:
            states.append(dict(entity_id=expected[key], **self.state(value,unit)))
        for entity in [expected['outdoor_battery'], expected['zones'][1]['battery'], expected['zones'][2]['battery']]:
            states.append(dict(entity_id=entity, state='off', attributes={'device_class':'battery'}))
        states.append(dict(entity_id=expected['zones'][2]['energy'], **self.state('4.25','kWh')))
        calls = []
        class FakeHA(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                calls.append(self.path)
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(states).encode())
            def do_POST(self):
                calls.append('POST'); self.send_response(500); self.end_headers()
        url = self.server(FakeHA)
        store = Store(Path(self.tmp.name)/'ecowitt.sqlite3')
        store.save_settings('beneden',dict(minimum=16,target=20,maximum=22))
        rt = Runtime(self.config,store,url+'/api','test-secret')
        rt.collect()
        data = rt.current()
        for zone in data['zones']:
            self.assertEqual(zone['samples']['temperature']['value'],21.5)
            self.assertEqual(zone['samples']['humidity']['value'],52)
        self.assertEqual(data['outdoor']['value'],12.5)
        self.assertEqual(data['outdoor_humidity']['value'],81)
        self.assertEqual(data['outdoor_dewpoint']['value'],9.3)
        self.assertEqual(data['outdoor_battery']['battery_status'],'normal')
        for zone in data['zones']:
            self.assertEqual(zone['samples']['dewpoint']['value'],11.2)
        self.assertEqual(data['zones'][1]['samples']['battery']['battery_status'],'normal')
        self.assertEqual(data['zones'][2]['samples']['energy']['value'],4.25)
        self.assertEqual(data['zones'][0]['settings']['target'],20)
        self.assertEqual(calls,['/api/states'])
        self.assertEqual(store.latest()['outdoor_humidity']['value'],81)
        again = Runtime(self.config,store,url+'/api','test-secret')
        self.assertEqual(again.config,rt.config)
        # Old snapshot remains readable during restart before the first poll.
        del data['outdoor_humidity']
        store.save(data,90)
        self.assertIsNone(again.current()['outdoor_humidity']['value'])

    def test_ecowitt_custom_bindings_and_unavailable_values(self):
        self.config.update(outdoor='sensor.custom_outside',outdoor_humidity='sensor.custom_rh')
        for zone in self.config['zones']:
            zone.update(temperature='sensor.custom_'+zone['id'],humidity='sensor.rh_'+zone['id'])
        self.config['zones'][2]['energy']='sensor.custom_energy'
        rt = Runtime(self.config,Store(Path(self.tmp.name)/'custom.sqlite3'),'','')
        self.assertEqual(rt.config,self.config)
        data = snapshot(rt.config,{'sensor.custom_rh':self.state('81','°C')},NOW)
        self.assertEqual(data['outdoor_humidity']['quality'],'unit_mismatch')
        self.assertIsNone(data['outdoor_humidity']['value'])
        self.assertIsNone(data['zones'][2]['samples']['energy']['value'])
        self.config['zones'][2].update(device='switch.other',energy='')
        rt = Runtime(self.config,rt.store,'','')
        self.assertEqual(rt.config['zones'][2]['energy'],'')

    def test_dewpoint_battery_upgrade_and_history(self):
        expected = copy.deepcopy(self.config)
        for key in ('outdoor_dewpoint', 'outdoor_battery'):
            self.config.pop(key)
        for zone in self.config['zones']:
            zone.pop('dewpoint'); zone.pop('battery')
        store = Store(Path(self.tmp.name)/'dewpoint.sqlite3')
        old = snapshot(self.config, {}, NOW-30)
        for zone in old['zones']:
            zone['samples'].pop('dewpoint'); zone['samples'].pop('battery')
        old.pop('outdoor_dewpoint'); old.pop('outdoor_battery')
        store.save(old, 90)
        rt = Runtime(self.config, store, '', '')
        self.assertEqual(rt.config, expected)
        self.assertIsNone(store.history(0)[0]['outdoor_dewpoint'])
        self.assertIsNone(store.history(0)[0]['zones'][0]['samples']['dewpoint'])
        self.assertEqual(len(rt.current()['zones']), 3)
        states = {expected['outdoor_dewpoint']: self.state('-2.5', '°C'),
                  expected['outdoor_battery']: dict(state='off', attributes={'device_class':'battery'})}
        for zone in expected['zones']:
            states[zone['dewpoint']] = self.state('0', '°C')
            if zone['battery']:
                states[zone['battery']] = dict(state='on', attributes={'device_class':'battery'})
        data = snapshot(rt.config, states, NOW)
        store.save(data, 90)
        again = Runtime(rt.config, store, '', '')
        self.assertEqual(again.current()['outdoor_dewpoint']['value'], -2.5)
        self.assertEqual(again.current()['outdoor_battery']['battery_status'], 'normal')
        self.assertEqual(store.history(0)[-1]['zones'][1]['samples']['battery']['battery_status'], 'low')
        self.assertEqual(data['zones'][0]['samples']['battery']['quality'], 'not_configured')
        self.assertEqual(data['zones'][0]['samples']['dewpoint']['value'], 0)
        expected['outdoor_dewpoint'] = 'sensor.custom_dewpoint'
        expected['zones'][1]['battery'] = 'binary_sensor.custom_battery'
        self.assertEqual(Runtime(expected, store, '', '').config, expected)
        self.assertEqual(again.control.records(), [])

    def test_battery_binary_semantics_and_dewpoint_failures(self):
        entity = 'binary_sensor.gw1200a_battery_2'
        for raw, quality, status in [('off','available','normal'),('on','available','low'),
                                     ('unknown','unknown',None),('unavailable','unavailable',None),
                                     ('Normaal','invalid',None),('50','invalid',None)]:
            with self.subTest(raw=raw):
                sample = battery_observation(entity, {entity:dict(state=raw, attributes={'device_class':'battery'})}, NOW)
                self.assertEqual((sample['quality'], sample['battery_status']), (quality,status))
        sample = battery_observation(entity, {entity:self.state('off')}, NOW)
        self.assertEqual(sample['quality'], 'device_class_mismatch')
        self.assertIsNone(sample['battery_status'])
        self.assertEqual(battery_observation(entity, {}, NOW)['quality'], 'missing')
        for raw, unit, quality in [('unknown','°C','unknown'),('nan','°C','invalid'),('12','°F','unit_mismatch')]:
            data = snapshot(self.config, {self.config['outdoor_dewpoint']:self.state(raw,unit)}, NOW)
            self.assertEqual(data['outdoor_dewpoint']['quality'], quality)
            self.assertIsNone(data['outdoor_dewpoint']['value'])

if __name__=='__main__':unittest.main()
