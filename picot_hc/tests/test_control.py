import json
import socket
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from picot_hc.__main__ import Runtime, handler
from picot_hc.core import Store


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
        self.calls, self.status, self.apply, self.drop, self.read_fail = [], 200, False, False, False
        self.unit = '°C'
        self.states = {}
        for entity in [self.config['cv'], *(z['device'] for z in self.config['zones'])]:
            self.states[entity] = {'entity_id': entity, 'state': 'off', 'last_updated': '2026-09-13T10:00:00Z',
                'attributes': {'hvac_modes': ['off','heat','dry'], 'temperature': 20,
                               'min_temp': 16, 'max_temp': 30, 'target_temp_step': .5,
                               'supported_features': 1, 'hvac_action': 'idle'}}
        outer = self
        class HA(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(503 if outer.read_fail else 200); self.end_headers()
                self.wfile.write(json.dumps({'unit_system': {'temperature':outer.unit}} if self.path == '/api/config' else list(outer.states.values())).encode())
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.calls.append((self.path, data))
                if outer.apply:
                    state = outer.states[data['entity_id']]
                    if 'hvac_mode' in data: state['state'] = data['hvac_mode']
                    elif 'temperature' in data: state['attributes']['temperature'] = data['temperature']
                    else: state['state'] = 'on' if self.path.endswith('turn_on') else 'off'
                if outer.drop:
                    self.connection.shutdown(socket.SHUT_RDWR); self.connection.close(); return
                self.send_response(outer.status); self.end_headers(); self.wfile.write(b'[]')
        self.url = self.server(HA) + '/api'
        self.store = Store(Path(self.tmp.name) / 'hc.sqlite3')
        self.runtime = Runtime(self.config, self.store, self.url, 'fake-secret')
        self.ctl = self.runtime.control

    def server(self, cls):
        server = ThreadingHTTPServer(('127.0.0.1',0),cls)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port)

    def payload(self, source='beneden', field='mode', value='heat'):
        return dict(request_id=str(uuid.uuid4()), source=source, field=field, value=value)

    def submit(self, payload=None):
        return self.ctl.submit(payload or self.payload(), 120)

    def test_ack_is_not_feedback_and_old_read_cannot_confirm(self):
        p = self.payload(); command = self.submit(p)
        self.assertEqual(command['status'], 'awaiting_feedback')
        self.assertIsNotNone(command['accepted'])
        entity = self.config['zones'][0]['device']
        self.assertEqual(self.calls, [('/api/services/climate/set_hvac_mode', {'entity_id':entity, 'hvac_mode':'heat'})])
        self.states[entity]['state'] = 'heat'
        self.ctl.observe(self.states, command['sent']-1, time.time())
        self.assertEqual(self.ctl.records()[0]['status'], 'awaiting_feedback')
        self.ctl.observe(self.states, time.time(), time.time())
        self.assertEqual(self.ctl.records()[0]['status'], 'confirmed')
        self.assertEqual(self.ctl.records()[0]['reported']['value'], 'heat')

    def test_idempotent_request_does_not_repeat_device_write(self):
        p = self.payload(); self.submit(p); self.submit(p)
        self.assertEqual(len(self.calls),1)
        p['value'] = 'dry'
        with self.assertRaises(ValueError): self.submit(p)
        self.assertEqual(len(self.calls),1)

    def test_pending_blocks_other_commands_but_off_preempts_even_if_report_still_off(self):
        self.submit()
        with self.assertRaises(ValueError): self.submit(self.payload(value='dry'))
        command = self.submit(self.payload(value='off'))
        self.assertEqual(command['status'], 'awaiting_feedback')
        self.assertEqual([c[1]['hvac_mode'] for c in self.calls], ['heat','off'])
        self.assertIn('superseded',[c['status'] for c in self.ctl.records()])

    def test_timeout_and_restart_do_not_replay(self):
        c = self.submit()
        self.ctl.sources(c['deadline']+1,120)
        self.assertEqual(self.ctl.records()[0]['status'],'timed_out')
        p = self.payload(source='boven'); self.submit(p)
        restarted = Runtime(self.config, self.store, self.url, 'fake-secret')
        self.assertEqual(restarted.control.records()[0]['status'],'interrupted')
        restarted.control.submit(p,120)
        self.assertEqual(len(self.calls),2)

    def test_temperature_validates_capability_unit_bounds_and_step(self):
        entity = self.config['cv']; self.states[entity]['state']='heat'
        for value in [15,31,20.25,True,float('nan')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.submit(self.payload('cv','temperature',value))
        self.unit='°F'
        with self.assertRaises(ValueError): self.submit(self.payload('cv','temperature',21))
        self.unit='°C'
        c=self.submit(self.payload('cv','temperature',21.5))
        self.assertEqual(self.calls,[('/api/services/climate/set_temperature',{'entity_id':entity,'temperature':21.5})])
        self.states[entity]['attributes']['temperature']=21
        self.ctl.observe(self.states,time.time(),time.time())
        self.assertEqual(self.ctl.records()[0]['status'],'awaiting_feedback')
        self.states[entity]['attributes']['temperature']=21.5
        self.ctl.observe(self.states,time.time(),time.time())
        self.assertEqual(self.ctl.records()[0]['status'],'confirmed')

    def test_confirmed_cv_step_when_ha_omits_it(self):
        entity = self.config['cv']
        self.states[entity]['attributes'] = {
            'hvac_modes': ['off', 'heat', 'auto'], 'min_temp': 5, 'max_temp': 30,
            'temperature': 6, 'current_temperature': 23.5, 'supported_features': 401}
        self.apply = True
        for mode, value in [('heat', 19.5), ('auto', 20.5)]:
            self.states[entity]['state'] = mode
            command = self.submit(self.payload('cv', 'temperature', value))
            self.ctl.observe(self.states, time.time(), time.time())
            self.assertEqual(self.ctl.records()[0]['status'], 'confirmed')
            self.assertEqual(self.calls[-1], ('/api/services/climate/set_temperature',
                             {'entity_id': entity, 'temperature': value}))
        for value in [4.5, 30.5, 20.25]:
            with self.assertRaises(ValueError):
                self.submit(self.payload('cv', 'temperature', value))
        self.assertEqual(len(self.calls), 2)
        # Explicit HA metadata takes precedence, including invalid metadata.
        for step in [1, 0]:
            self.states[entity]['attributes']['target_temp_step'] = step
            with self.assertRaises(ValueError):
                self.submit(self.payload('cv', 'temperature', 21.5))
        other = self.config['zones'][0]['device']
        del self.states[other]['attributes']['target_temp_step']
        self.ctl.observe(self.states, time.time(), time.time())
        self.assertFalse(next(s for s in self.ctl.sources(time.time(), 120)
                              if s['entity_id'] == other)['temperature_supported'])

    def test_switch_on_and_already_set_are_distinct(self):
        entity=self.config['zones'][2]['device']
        c=self.submit(self.payload('badkamer','state','off'))
        self.assertEqual(c['status'],'already_set'); self.assertIsNone(c['sent']); self.assertEqual(self.calls,[])
        self.submit(self.payload('badkamer','state','on'))
        self.assertEqual(self.calls,[('/api/services/switch/turn_on',{'entity_id':entity})])

    def test_missing_source_unsupported_mode_and_failed_read_never_write(self):
        for p in [self.payload(source='arbitrary'),self.payload(value='cool'),self.payload(field='service',value='turn_on')]:
            with self.assertRaises(ValueError): self.submit(p)
        self.states[self.config['zones'][0]['device']]['state']='unavailable'
        with self.assertRaises(ValueError): self.submit()
        self.read_fail=True
        with self.assertRaises(ValueError): self.submit()
        self.assertEqual(self.calls,[])

    def test_storage_failure_prevents_dispatch(self):
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER deny_command BEFORE INSERT ON commands BEGIN SELECT RAISE(ABORT,'blocked'); END")
        import sqlite3
        with self.assertRaises(sqlite3.Error): self.submit()
        self.assertEqual(self.calls,[])

    def test_http_rejection_and_ambiguous_transport_are_not_success_or_retried(self):
        self.status=400
        self.assertEqual(self.submit()['status'],'failed')
        self.status=200; self.drop=True; self.apply=True
        c=self.submit(self.payload(source='boven'))
        self.assertEqual(c['status'],'uncertain')
        self.ctl.observe(self.states,time.time(),time.time())
        self.assertEqual(self.ctl.records()[0]['status'],'confirmed')
        self.assertEqual(len(self.calls),2)

    def test_dashboard_post_requires_csrf_and_ingress_and_exposes_no_token(self):
        url=self.server(handler(self.runtime,False))
        p=self.payload(); raw=json.dumps(p).encode()
        with self.assertRaises(HTTPError) as cm:
            urlopen(Request(url+'/api/commands',data=raw,headers={'Content-Type':'application/json'}))
        self.assertEqual(cm.exception.code,403); self.assertEqual(self.calls,[])
        headers={'Content-Type':'application/json','X-HC-CSRF':self.runtime.csrf_token}
        response=json.load(urlopen(Request(url+'/api/commands',data=raw,headers=headers)))
        self.assertEqual(response['command']['status'],'awaiting_feedback')
        self.assertNotIn('fake-secret',json.dumps(response))
        ingress=self.server(handler(self.runtime,True))
        with self.assertRaises(HTTPError) as cm:
            urlopen(Request(ingress+'/api/commands',data=raw,headers=headers))
        self.assertEqual(cm.exception.code,403)
        self.assertEqual(len(self.calls),1)

    def test_stale_projection_disables_buttons(self):
        self.ctl.observe(self.states, time.time()-300, time.time()-300)
        self.assertTrue(all(not s['available'] for s in self.ctl.sources(time.time(),120)))

    def test_failed_off_intent_does_not_supersede_the_existing_command(self):
        import sqlite3
        first = self.submit()
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER deny_new BEFORE INSERT ON commands WHEN NEW.id != '" + first['id'] + "' BEGIN SELECT RAISE(ABORT,'blocked'); END")
        with self.assertRaises(sqlite3.Error): self.submit(self.payload(value='off'))
        self.assertEqual(self.ctl.records()[0]['status'], 'awaiting_feedback')
        self.assertEqual(len(self.calls), 1)
