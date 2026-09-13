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

from picot_hc.core import Store, snapshot, validate, prices, fetch_states, observation
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
        self.assertEqual(cm.exception.code,501)

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

if __name__=='__main__':unittest.main()
