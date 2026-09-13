import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from picot_hc.__main__ import Runtime
from picot_hc.core import Store
from picot_hc.weather import WeatherReader, fetch_forecast, forecast_view, weather_now

NOW = 1789293600.0
ENTITY = 'weather.buienradar'

class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
        self.state = {'entity_id':ENTITY, 'state':'cloudy', 'last_updated':'2026-09-13T10:00:00Z',
                      'attributes':{'temperature':20.7, 'temperature_unit':'°C', 'humidity':81,
                                    'wind_speed':9.72, 'wind_speed_unit':'km/h', 'precipitation_unit':'mm'}}
        self.rows = [{'datetime':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), 'condition':'rainy',
                      'temperature':18, 'templow':11, 'precipitation':0, 'wind_speed':12}]
        self.calls = []; self.fail = False

    def server(self, cls):
        s = ThreadingHTTPServer(('127.0.0.1',0),cls)
        threading.Thread(target=s.serve_forever,daemon=True).start()
        self.addCleanup(s.server_close); self.addCleanup(s.shutdown)
        return 'http://127.0.0.1:' + str(s.server_port)

    def ha(self):
        outer = self
        class HA(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps([outer.state]).encode())
            def do_POST(self):
                outer.calls.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(503 if outer.fail else 200); self.end_headers()
                self.wfile.write(json.dumps({'service_response':{ENTITY:{'forecast':outer.rows}}}).encode())
        return self.server(HA) + '/api'

    def test_attributes_and_missing_values(self):
        w = weather_now(ENTITY,{ENTITY:self.state},NOW)
        self.assertEqual(w['metrics']['temperature']['value'],20.7)
        self.assertEqual(w['metrics']['humidity']['value'],81)
        self.assertEqual(w['metrics']['wind_speed']['unit'],'km/h')
        self.assertIsNone(w['metrics']['apparent_temperature']['value'])
        self.state['state']='unavailable'
        self.assertIsNone(weather_now(ENTITY,{ENTITY:self.state},NOW)['metrics']['temperature']['value'])
        self.assertEqual(weather_now(ENTITY,{},NOW)['condition']['quality'],'missing')

    def test_real_http_cache_restart_failure_isolation(self):
        url=self.ha(); store=Store(Path(self.tmp.name)/'hc.sqlite3')
        rt=Runtime(self.config,store,url,'fake-token'); rt.collect(); rt.collect()
        self.assertEqual(self.calls,[('/api/services/weather/get_forecasts?return_response',{'entity_id':ENTITY,'type':'daily'})])
        w=rt.current()['weather']['forecast']
        self.assertEqual(w['rows'][0]['precipitation'],0)
        self.assertIsNone(w['rows'][0]['precipitation_probability'])
        self.assertEqual(w['temperature_unit'],'°C')
        self.assertNotIn('fake-token',json.dumps(rt.current()))
        reopened=Runtime(self.config,Store(store.path),url,'fake-token'); self.fail=True; reopened.collect()
        self.assertEqual(reopened.connection,'connected')
        f=reopened.current()['weather']['forecast']
        self.assertTrue(f['stale']); self.assertEqual(f['rows'][0]['temperature'],18)
        self.assertIn('mislukt',f['error'])

    def test_invalid_timestamp(self):
        url=self.ha(); self.rows[0]['datetime']='2026-09-14T00:00:00'
        with self.assertRaises(ValueError): fetch_forecast(url,'fake-token',ENTITY)
        w=WeatherReader(ENTITY).collect({ENTITY:self.state},NOW,url,'fake-token')['forecast']
        self.assertTrue(w['stale']); self.assertEqual(w['rows'],[])

    def test_expiry_and_past_days(self):
        f={'received':NOW-7201,'rows':[{'time':NOW-86400},{'time':NOW+86400}]}
        result=forecast_view(f,NOW)
        self.assertTrue(result['stale']); self.assertEqual(result['rows'],[{'time':NOW+86400}])
        self.assertEqual(len(f['rows']),2)

    def test_redirect_does_not_forward_credentials(self):
        calls=[]
        class Destination(BaseHTTPRequestHandler):
            def do_GET(self): calls.append('GET')
            def do_POST(self): calls.append('POST')
        target=self.server(Destination)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                self.send_response(302); self.send_header('Location',target); self.end_headers()
        with self.assertRaises(HTTPError): fetch_forecast(self.server(Redirect),'fake-token',ENTITY)
        self.assertEqual(calls,[])
