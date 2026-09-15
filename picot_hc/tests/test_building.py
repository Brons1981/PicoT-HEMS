import copy
import json
import tempfile
import unittest
from pathlib import Path

from picot_hc.building import building_observation
from picot_hc.core import Store, snapshot
from picot_hc.schedule import DOOR


ROOT = Path(__file__).resolve().parents[1]
NOW = 1789500000.0


class BuildingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'options.example.json').read_text())
        self.states = {}
        for zone, temperature in zip(self.config['zones'], (21, 19, 10)):
            self.states[zone['temperature']] = self.state(temperature, '°C')
        self.states[self.config['outdoor']] = self.state(10, '°C')

    def state(self, value, unit=None):
        return dict(state=str(value), attributes={'unit_of_measurement': unit},
                    last_updated='2026-09-15T19:00:00Z', last_reported='2026-09-15T19:01:00Z')

    def collect(self):
        data = snapshot(self.config, self.states, NOW)
        data['building'] = building_observation(self.config, self.states, NOW, data, DOOR)
        return data

    def test_delta_uses_measured_outdoor_and_preserves_source_times(self):
        data = self.collect()
        self.assertEqual([z['delta_t_k'] for z in data['building']['zones']], [11, 9, 0])
        self.assertEqual(data['zones'][0]['samples']['temperature']['source_reported'], '2026-09-15T19:01:00Z')
        self.assertEqual(data['zones'][0]['samples']['temperature']['source_updated'], '2026-09-15T19:00:00Z')
        self.states[self.config['outdoor']]['state'] = '25'
        self.assertEqual(self.collect()['building']['zones'][0]['delta_t_k'], -4)
        for raw, unit in [('unavailable', '°C'), ('10', '°F'), ('nan', '°C')]:
            self.states[self.config['outdoor']] = self.state(raw, unit)
            self.assertIsNone(self.collect()['building']['zones'][0]['delta_t_k'])

    def test_source_mode_activity_and_door_are_independent_observations(self):
        cv = self.config['cv']
        self.states[cv] = self.state('heat')
        self.states[cv]['attributes'].update(hvac_action='idle', temperature=20)
        self.states[DOOR] = self.state('on')
        data = self.collect()['building']
        source = next(s for s in data['sources'] if s['entity_id'] == cv)
        self.assertEqual(source['zones'], ['beneden', 'boven'])
        self.assertEqual(source['mode']['value'], 'heat')
        self.assertEqual(source['activity']['value'], 'idle')
        self.assertEqual(source['target']['value'], 20)
        self.assertIsNone(source['target']['unit'])  # No invented temperature unit.
        self.assertEqual(data['back_door']['value'], 'on')
        self.states[cv]['attributes']['hvac_action'] = 'heating'
        self.assertEqual(next(s for s in self.collect()['building']['sources'] if s['entity_id'] == cv)['activity']['value'], 'heating')
        del self.states[cv]['attributes']['hvac_action']
        self.states[DOOR]['state'] = 'unknown'
        data = self.collect()['building']
        self.assertIsNone(next(s for s in data['sources'] if s['entity_id'] == cv)['activity']['value'])
        self.assertIsNone(data['back_door']['value'])

    def test_recording_does_not_modify_inputs(self):
        before = copy.deepcopy(self.states)
        self.collect()
        self.assertEqual(self.states, before)

    def test_paged_export_preserves_old_records_and_bounds_new_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'hc.sqlite3')
            old = snapshot(self.config, self.states, NOW - 30)
            old['csrf_token'] = 'must-not-be-exported'
            store.save(old, 90)
            data = self.collect()
            store.save(data, 90)
            reopened = Store(store.path)
            rows = list(reopened.building_records(NOW, page_size=1))
            self.assertEqual(len(rows), 2)
            self.assertIsNone(rows[0]['building'])
            self.assertNotIn('csrf_token', rows[0])
            self.assertEqual(rows[1]['building']['zones'][0]['delta_t_k'], 11)
            self.assertEqual(rows[1]['outdoor']['value'], 10)
            data['collected'] = NOW + 30
            reopened.save(data, 90)
            self.assertEqual(len(list(reopened.building_records(NOW, page_size=1))), 2)
            self.assertEqual(reopened.latest()['building']['version'], 1)
