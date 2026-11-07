import json
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from picot_hc.control import Control
from picot_hc.core import Store, fetch_states
from picot_hc.energy_model import meter_context
from picot_hc.startup_energy import StartupEnergy
from test_startup_energy import inputs


class CounterReportsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
        self.store = Store(Path(tmp.name) / 'hc.sqlite')
        self.ctl = Control(self.config, self.store, '', '')
        self.states, self.calls, self.template_calls = {}, [], []
        self.template_reports = None

    def setup_sample(self, age=525):
        self.now = 1793898590.0 + age
        self.zone = next(z for z in self.config['zones'] if z['id'] == 'beneden')
        self.entity = self.zone['energy']
        stamp = datetime.fromtimestamp(self.now-age, timezone.utc).isoformat()
        self.states[self.entity] = dict(entity_id=self.entity, state='2357.397',
            last_updated=stamp, last_reported=stamp,
            attributes={'unit_of_measurement': 'kWh'})
        self.view, self.plan, self.command = inputs(self.now)
        self.plan['learning_context'] = dict(valid=True, indoor=18, outdoor=10,
                                           identity='same-device')
        self.plan['sources']['beneden']['available'] = True
        self.plan['sources']['cv'] = dict(state='off', available=True, pending=False)
        self.meter = dict(status='available', power_w=0, source_id='meter')

    def read_sample(self):
        def response(request, timeout):
            if request.full_url.endswith('/states'):
                data = list(self.states.values())
            else:
                self.assertTrue(request.full_url.endswith('/template'))
                payload = json.loads(request.data)
                self.template_calls.append(payload)
                ids = json.loads(payload['template'].split('{% for id in ')[1].split(' %}')[0])
                reports = self.template_reports if self.template_reports is not None else list(self.states.values())
                data = [r for r in reports if r['entity_id'] in ids]
            return io.BytesIO(json.dumps(data).encode())
        with patch('picot_hc.core.build_opener') as opener:
            opener.return_value.open.side_effect = response
            states = fetch_states('http://ha.test/api', 'fake-secret', self.ctl.report_entities)
        return meter_context(self.config, states, self.plan, self.meter, self.now)

    def test_unchanged_counter_with_fresh_report_starts_full_measurement(self):
        for age in (301, 525):
            with self.subTest(age=age):
                self.setup_sample(age)
                fresh = datetime.fromtimestamp(self.now, timezone.utc).isoformat()
                self.template_reports = [dict(self.states[self.entity], last_reported=fresh)]
                initial = self.read_sample()
                self.assertIsNotNone(initial)
                self.assertEqual(initial['energy_wh'], 2357397)
                ids = json.loads(self.template_calls[-1]['template'].split('{% for id in ')[1].split(' %}')[0])
                self.assertIn(self.entity, ids)
                model = StartupEnergy(self.store)
                model.prepare(initial, self.view, self.plan, ('beneden', 'heating', 20), self.now)
                self.plan['owned'] = dict(beneden=dict(command=self.command['id']))
                model.observe(initial, self.view, self.plan, [self.command], self.now)
                self.assertIsNotNone(model.model.session)
                self.assertEqual(model.model.session['first']['energy_wh'], 2357397)
                self.assertEqual(self.calls, [])

    def test_missing_direct_report_cannot_use_fresh_cached_counter(self):
        self.setup_sample(age=0)
        self.template_reports = []
        self.assertIsNone(self.read_sample())

    def test_stale_future_and_unknown_counter_still_rejected(self):
        for age, value in ((91, '2357.397'), (-1, '2357.397'), (0, 'unknown')):
            with self.subTest(age=age, value=value):
                self.setup_sample(age)
                self.states[self.entity]['state'] = value
                self.assertIsNone(self.read_sample())

    def test_missing_sample_is_explained_without_inventing_measurements(self):
        self.setup_sample()
        model = StartupEnergy(self.store)
        model.prepare(None, self.view, self.plan, ('beneden', 'heating', 20), self.now)
        self.assertIsNone(model.baseline)
        self.assertEqual(model.model.records, [])
        self.assertEqual(model.model.events[-1]['reason'], 'startup_baseline_measurement_unavailable')
        self.assertIn('beginmeting', model.view(None, self.now)['last_issue'])
        model.prepare(None, self.view, self.plan, ('beneden', 'heating', 20), self.now+30)
        self.assertEqual(len(model.model.events), 1)

    def test_missing_baseline_after_start_is_explained(self):
        self.setup_sample(age=0)
        sample = self.read_sample()
        model = StartupEnergy(self.store)
        self.plan['owned'] = dict(beneden=dict(command=self.command['id']))
        model.observe(sample, self.view, self.plan, [self.command], self.now)
        self.assertIsNone(model.model.session)
        self.assertEqual(model.model.events[-1]['reason'], 'startup_baseline_missing')

    def test_idle_poll_without_start_does_not_log_failure(self):
        self.setup_sample()
        model = StartupEnergy(self.store)
        model.prepare(None, self.view, self.plan, None, self.now)
        self.assertEqual(model.model.events, [])

    def test_completed_start_does_not_become_missing_baseline_on_next_poll(self):
        from test_startup_energy import run
        from test_energy_proposals import NOW, sample
        model = StartupEnergy(self.store)
        run(model, NOW)
        self.assertEqual(len(model.model.records), 1)
        view, plan, command = inputs(NOW)
        plan['owned'] = dict(beneden=dict(command=command['id']))
        plan['sources']['beneden']['state'] = 'heat'
        command['status'] = 'confirmed'
        for reader in (model, StartupEnergy(self.store)):
            reader.observe(sample(), view, plan, [command], NOW+2100)
            self.assertEqual(reader.model.events[-1]['kind'], 'completed')
            self.assertIsNone(reader.view(sample(), NOW+2100)['last_issue'])
