"""Outlook is visible while HC is off and cannot alter a heating decision."""
from test_downstairs_comfort import DownstairsComfortTests
from picot_hc.core import snapshot
from picot_hc.energy_outlook import ENTITY


class OutlookHCTests(DownstairsComfortTests):
    def test_collector_learns_standby_before_heat_demand_without_commands(self):
        import copy
        from unittest.mock import patch
        self.settings(enabled=True, learning_enabled=True, door_close_seconds=0,
            initial_preheat_minutes=45, setback_temperature=17,
            windows=[dict(day=3, start='19:30', end='22:00', target=20, hard=True)])
        self.temperature('beneden', 18)
        with patch('picot_hc.__main__.fetch_states', side_effect=lambda *args: copy.deepcopy(self.states)), \
                patch.object(self.runtime.weather, 'collect', return_value={}), \
                patch.object(self.runtime.energy_proposals.publisher, 'submit'), \
                patch.object(self.runtime.energy_publisher, 'submit'):
            for minute in range(16):
                if minute:
                    self.now += 60
                for zone in self.config['zones']:
                    self.states[zone['temperature']]['last_reported'] = self.stamp(self.now)
                for meter, value, unit in (
                    (self.config['outdoor'], 10, '°C'),
                    ('sensor.kwh_meter_airco_vermogen', 10, 'W'),
                    ('sensor.kwh_meter_airco_energie_import', 100+minute/6000, 'kWh')):
                    self.states[meter] = dict(state=str(value), last_reported=self.stamp(self.now),
                                              attributes={'unit_of_measurement':unit})
                self.runtime.collect()
        self.assertEqual(self.runtime.connection, 'connected')
        self.assertAlmostEqual(self.runtime.energy_proposals.standby.estimate(self.now), 14.5)
        self.assertEqual(self.runtime.current()['energy_proposals']['status'], 'waiting')
        self.assertEqual(self.calls, [])

    def test_collector_measures_full_start_including_delayed_confirmation(self):
        import copy
        from unittest.mock import patch
        self.settings(enabled=True, learning_enabled=True, door_close_seconds=0,
            initial_preheat_minutes=45, setback_temperature=17,
            windows=[dict(day=3, start='19:00', end='22:00', target=20, hard=True)])
        self.temperature('beneden', 18)
        self.now += 900
        entity = self.ctl.bindings['beneden']['entity_id']
        used, previous = 0, 0
        with patch('picot_hc.__main__.fetch_states', side_effect=lambda *args: copy.deepcopy(self.states)), \
                patch.object(self.runtime.weather, 'collect', return_value={}), \
                patch.object(self.runtime.energy_proposals.publisher, 'submit'), \
                patch.object(self.runtime.energy_publisher, 'submit'):
            for minute in range(35):
                if minute:
                    self.now += 60
                power = 0 if minute == 0 else 300 if minute == 1 else 1200
                if minute:
                    used += (previous+power)/2/60
                previous = power
                self.states[entity]['state'] = 'off' if minute < 2 else 'heat'
                self.temperature('beneden', min(20, 18+max(0, minute-2)/15))
                for zone in self.config['zones']:
                    self.states[zone['temperature']]['last_reported'] = self.stamp(self.now)
                for meter, value, unit in (
                    (self.config['outdoor'], 10, '°C'),
                    ('sensor.kwh_meter_airco_vermogen', power, 'W'),
                    ('sensor.kwh_meter_airco_energie_import', 100+used/1000, 'kWh')):
                    self.states[meter] = dict(state=str(value), last_reported=self.stamp(self.now),
                                              attributes={'unit_of_measurement':unit})
                self.runtime.collect()
                self.assertEqual(self.runtime.connection, 'connected')
        records = self.runtime.startup_energy.model.records
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0]['used_wh'], 655)
        self.assertEqual(records[0]['confirmation_delay_seconds'], 120)
        self.assertEqual(records[0]['duration_seconds'], 2040)
        self.assertEqual(self.runtime.current()['startup_energy']['completed_sessions'], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]['hvac_mode'], 'heat')

    def test_runtime_measures_preheat_energy_without_new_commands(self):
        from unittest.mock import patch
        self.settings(enabled=True, learning_enabled=True, door_close_seconds=0,
            initial_preheat_minutes=45, setback_temperature=17,
            windows=[dict(day=3, start='19:00', end='22:00', target=20, hard=True)])
        self.temperature('beneden', 18)
        self.poll(900)
        self.poll()
        self.runtime.connection = 'connected'
        with patch.object(self.runtime.energy_proposals.publisher, 'submit'):
            for minute in range(33):
                self.temperature('beneden', min(20, 18+minute/15))
                self.poll(60)
                for entity, value, unit in (
                    (self.config['outdoor'], 10, '°C'),
                    ('sensor.kwh_meter_airco_vermogen', 1200, 'W'),
                    ('sensor.kwh_meter_airco_energie_import', 100+minute*.02, 'kWh')):
                    self.states[entity] = dict(state=str(value), last_reported=self.stamp(self.now),
                                               attributes={'unit_of_measurement':unit})
                self.ctl.observe(self.states, self.now, self.now)
                before = list(self.calls)
                self.runtime._energy_advice()
                self.assertEqual(self.calls, before)
            current = self.runtime.current()['warmup_energy']
            self.assertEqual(current['completed_sessions'], 1)
            self.assertFalse(current['execution_authorized'])
            self.assertAlmostEqual(self.runtime.warmup_energy.records[0]['used_wh'], 640)

    def test_runtime_proposes_maintaining_heat_and_withdraws_when_schema_disabled(self):
        from unittest.mock import patch
        from picot_hc.energy_measurement import measurement
        from picot_hc.energy_model import context
        self.settings(enabled=True, learning_enabled=True, door_close_seconds=0,
            windows=[dict(day=3, start='17:00', end='22:00', target=20, hard=False)])
        self.temperature('beneden', 19)
        self.poll(advance=121)
        self.poll()
        self.temperature('beneden', 20)
        self.poll()
        self.states[self.config['outdoor']] = dict(state='10', last_reported=self.stamp(self.now),
            attributes={'unit_of_measurement':'°C'})
        self.states['sensor.kwh_meter_airco_vermogen'] = dict(state='600', last_reported=self.stamp(self.now),
            attributes={'unit_of_measurement':'W'})
        self.states['sensor.kwh_meter_airco_energie_import'] = dict(state='100', last_reported=self.stamp(self.now),
            attributes={'unit_of_measurement':'kWh'})
        self.ctl.observe(self.states, self.now, self.now)
        self.runtime.connection = 'connected'
        meter = measurement(self.config, self.states, self.now)
        current = context(self.config, self.states, self.heat.view(self.config, self.now), meter, self.now)
        self.assertIsNotNone(current)
        for minute in range(63):
            self.runtime.energy_proposals.model.observe(dict(current, energy_wh=100000+minute*10),
                self.now-3720+minute*60)
        self.states[ENTITY] = dict(state='ready', attributes=dict(
            contract='hems-energy-outlook:v1', snapshot_id='example', generated_at=self.stamp(self.now),
            valid_until=self.stamp(self.now+180), status='ready', advisory_only=True,
            approval_required=True, budgets_additive=False, available_additional_energy_wh=None,
            horizon_start=self.stamp(self.now), horizon_end=self.stamp(self.now+3600), storage_floor_wh=800,
            projected_minimum_margin_wh=100, slots=[dict(starts_at=self.stamp(self.now),
                ends_at=self.stamp(self.now+3600), storage_minimum_wh=900, storage_margin_wh=100,
                pv_export_wh=0, grid_import_wh=100, confidence=.8)],
            replacement_basis=dict(status='ready', basis_id='f'*64, source_id=meter['source_id'],
                starts_at=self.stamp(self.now), ends_at=self.stamp(self.now+3600),
                demand_basis='replace_controlled_load', execution_authorized=False)))
        self.ctl.observe(self.states, self.now, self.now)
        before = list(self.calls)
        with patch.object(self.runtime.energy_proposals.publisher, 'submit') as publish:
            self.runtime._energy_advice()
            self.assertEqual(publish.call_args.args[0]['state'], 'requested')
            self.assertEqual(self.runtime.current()['energy_proposals']['status'], 'proposed')
            self.settings(enabled=False)
            self.runtime._energy_advice()
            self.assertEqual(publish.call_args.args[0]['state'], 'withdrawn')
        self.assertEqual(self.calls, before)

    def test_runtime_exposes_automatic_proposal_status_without_climate_actions(self):
        self.assertEqual(self.runtime.current()['energy_proposals']['status'], 'waiting')
        self.assertEqual(self.runtime.current()['start_intent']['status'], 'waiting')
        self.assertFalse(self.runtime.current()['start_intent']['execution_authorized'])
        self.assertEqual(self.calls, [])

    def test_collector_records_and_publishes_meter_with_heating_disabled(self):
        from unittest.mock import patch
        self.heat.update(dict(revision=self.heat.data['revision'], settings=dict(self.heat.data['settings'], enabled=False)))
        self.states['sensor.kwh_meter_airco_vermogen'] = dict(state='1500',
            last_reported=self.stamp(self.now), attributes={'unit_of_measurement':'W'})
        with patch('picot_hc.__main__.fetch_states', return_value=self.states), \
                patch.object(self.runtime.weather, 'collect', return_value={}), \
                patch.object(self.runtime.energy_proposals.publisher, 'submit'), \
                patch.object(self.runtime.energy_publisher, 'submit') as publish:
            self.runtime.collect()
        self.assertEqual(self.runtime.connection, 'connected')
        self.assertEqual(self.store.latest()['energy_measurement']['power_w'], 1500)
        self.assertEqual(publish.call_args.args[0]['power_w'], 1500)
        self.assertEqual(self.calls, [])

    def test_runtime_exposes_outlook_when_heating_disabled_without_writes(self):
        self.heat.update(dict(revision=self.heat.data['revision'], settings=dict(self.heat.data['settings'], enabled=False)))
        self.runtime.connection = 'connected'
        self.states[ENTITY] = dict(state='ready', attributes=dict(
            contract='hems-energy-outlook:v1', snapshot_id='example', generated_at=self.stamp(self.now),
            valid_until=self.stamp(self.now+180), status='ready', advisory_only=True,
            approval_required=True, budgets_additive=False, available_additional_energy_wh=None,
            horizon_start=self.stamp(self.now), horizon_end=self.stamp(self.now+3600), storage_floor_wh=800,
            projected_minimum_margin_wh=100, slots=[dict(starts_at=self.stamp(self.now),
                ends_at=self.stamp(self.now+3600), storage_minimum_wh=900, storage_margin_wh=100,
                pv_export_wh=0, grid_import_wh=100, confidence=.8)]))
        self.ctl.observe(self.states, self.now, self.now)
        self.store.save(snapshot(self.config, self.states, self.now), 90)
        before = self.heat.plan(self.config, self.now)['desired']
        current = self.runtime.current()
        self.assertEqual(current['energy_outlook']['status'], 'ready')
        self.assertFalse(current['heating']['enabled'])
        self.assertEqual(before, current['heating']['desired'])
        self.assertEqual(self.calls, [])
        self.runtime.connection = 'disconnected'
        self.assertEqual(self.runtime.current()['energy_outlook']['status'], 'unavailable')


for _name in dir(DownstairsComfortTests):
    if _name.startswith('test_') and _name not in OutlookHCTests.__dict__:
        setattr(OutlookHCTests, _name, None)
