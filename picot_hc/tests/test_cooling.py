"""Cooling evidence and bounded downstairs setpoint decisions."""
from test_downstairs_comfort import DownstairsComfortTests, NOW


class CoolingTests(DownstairsComfortTests):
    def configure(self, **extra):
        self.settings(enabled=True, learning_enabled=True, adaptive_setback_enabled=True,
            coast_enabled=True, max_coast_minutes=60, setback_temperature=17,
            windows=[dict(day=3, start='18:00', end='22:00', target=20, hard=False)],
            optimization_band=.5, **extra)
        self.outdoor(10)

    def outdoor(self, value):
        entity = self.config['outdoor']
        self.states[entity] = dict(entity_id=entity, state=str(value),
            attributes={'unit_of_measurement': '\u00b0C'}, last_reported=self.stamp(self.now))

    def poll(self, advance=60):
        if self.config['outdoor'] in self.states:
            self.states[self.config['outdoor']]['last_reported'] = self.stamp(self.now+advance)
        return super().poll(advance)

    def measured_cooling(self):
        # Real sequence: both sources off, fresh sensors, closed door. At 21 C,
        # there is no heat demand. An hour cools 0.3 K, preceded by settling.
        self.configure()
        self.temperature('beneden', 21)
        self.poll()
        for minute in range(1, 81):
            self.temperature('beneden', 21-min(60, max(0, minute-20))*.005)
            self.poll()

    def test_initial_setback_is_cautious_and_manual_mode_unchanged(self):
        self.configure()
        plan = self.poll(4*3600)
        self.assertEqual(plan['zones']['beneden']['target'], 19)
        self.settings(enabled=False, thermostat_temperature=18)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 18)

    def test_cooling_evidence_allows_coast_inside_margin(self):
        self.measured_cooling()
        count = self.heat.view(self.config, self.now)['learning_status']['cooling_samples']
        self.assertGreaterEqual(count, 3)
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        plan = self.poll()
        self.assertEqual(plan['zones']['beneden']['target'], 19.5)
        self.assertEqual(plan['learning_status']['phase'], 'coast')
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))

    def test_no_evidence_does_not_coast(self):
        self.configure()
        self.temperature('beneden', 20)
        plan = self.poll(3*3600+30*60)
        self.assertEqual(plan['zones']['beneden']['target'], 20)

    def test_open_door_never_trains(self):
        from picot_hc.schedule import DOOR
        self.configure()
        self.temperature('beneden', 21)
        self.states[DOOR]['state'] = 'on'
        for _ in range(25):
            self.poll()
        self.assertEqual(self.heat.view(self.config, self.now)['learning_status']['cooling_samples'], 0)

    def test_unknown_heat_activity_and_gaps_do_not_train(self):
        self.configure()
        self.temperature('beneden', 19)
        self.poll(121)  # HC owns this heat command; no hvac_action is available.
        self.temperature('beneden', 21)
        for minute in range(50):
            self.temperature('beneden', 21-minute*.005)
            self.poll()
        self.assertEqual(self.heat.view(self.config, self.now)['learning_status']['cooling_samples'], 0)
        self.assertIsNone(self.heat.learning.cooling.segment)

    def test_cold_weather_hard_window_and_stale_sensor_prevent_coast(self):
        self.measured_cooling()
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        self.outdoor(0)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 20)
        self.outdoor(10)
        self.states[self.config['outdoor']]['last_reported'] = self.stamp(self.now-10000)
        self.ctl.observe(self.states, self.now, self.now)
        self.assertEqual(self.heat.view(self.config, self.now)['zones']['beneden']['target'], 20)
        self.settings(windows=[dict(day=3, start='18:00', end='22:00', target=20, hard=True)])
        self.assertEqual(self.poll()['zones']['beneden']['target'], 20)

    def test_coast_restores_comfort_and_does_not_retry_same_window(self):
        self.measured_cooling()
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 19.5)
        self.temperature('beneden', 19.6)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 20)
        self.temperature('beneden', 20.1)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 20)

    def test_coast_does_not_stop_owned_source_with_whole_degree_step(self):
        self.measured_cooling()
        self.temperature('beneden', 19)
        self.poll()
        entity = self.ctl.bindings['beneden']['entity_id']
        self.states[entity]['attributes']['target_temp_step'] = 1
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        plan = self.poll()
        self.assertEqual(plan['zones']['beneden']['target'], 20)
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))

    def test_three_successes_deepen_setback_and_failure_backs_off(self):
        from datetime import datetime, timedelta
        from picot_hc.schedule import TZ, wall_time
        self.measured_cooling()
        self.settings(windows=[dict(day=day, start='18:00', end='22:00', target=20, hard=False)
                               for day in range(7)])
        for day in range(1, 5):
            date = datetime.fromtimestamp(NOW, TZ).date()+timedelta(days=day)
            deadline = wall_time(date, 18*60)
            self.now = deadline-46*60
            self.states[self.config['price_entity']]['attributes']['raw_today'] = [
                dict(start=self.stamp(deadline-3600), end=self.stamp(deadline+86400), value=.25)]
            self.temperature('beneden', 18.5)
            self.poll()
            for minute in range(1, 46):
                self.temperature('beneden', 18.5 if day == 4 else 18.5+minute/30)
                self.poll()
            depth = self.heat.view(self.config, self.now)['learning_status']['setback_depth']
            self.assertEqual(depth, 1.5 if day == 3 else 1)
            if day == 3:
                self.now = wall_time(date, 22*60)
                self.assertEqual(self.poll()['zones']['beneden']['target'], 18.5)
                self.poll()  # Confirm the lower setpoint before skipping to tomorrow.
        self.now = wall_time(date, 22*60)
        plan = self.poll()
        self.assertGreaterEqual(plan['zones']['beneden']['target'], 17)
        self.assertEqual(plan['zones']['beneden']['target'], 19)

    def test_cooling_persists_but_does_not_bridge_restart(self):
        from picot_hc.cooling import Cooling
        self.measured_cooling()
        restored = Cooling(self.store)
        plan = self.heat.view(self.config, self.now)
        self.assertGreaterEqual(restored.estimate(plan['learning_context'], self.now)['cooling_samples'], 3)
        self.assertIsNone(restored.segment)
        self.assertIsNone(restored.estimate(plan['learning_context'], self.now+8*86400)['cooling_rate'])

    def test_floor_validation_and_adjacent_comfort(self):
        self.measured_cooling()
        with self.assertRaises(ValueError):
            self.settings(max_coast_minutes=61)
        with self.assertRaises(ValueError):
            self.settings(coast_enabled=1)
        self.settings(setback_temperature=19.5)
        self.now = NOW+4*3600
        self.assertEqual(self.poll()['zones']['beneden']['target'], 19.5)
        self.settings(setback_temperature=17, windows=[
            dict(day=3, start='18:00', end='22:00', target=20, hard=False),
            dict(day=3, start='22:00', end='23:00', target=20, hard=False)])
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 20)

    def test_owned_airco_receives_lower_setpoint_without_off(self):
        self.measured_cooling()
        self.temperature('beneden', 19)
        self.poll()
        self.poll()
        self.now = NOW+3*3600+30*60
        self.temperature('beneden', 20)
        self.assertEqual(self.poll()['zones']['beneden']['target'], 19.5)
        self.assertTrue(any(p.get('temperature') == 19.5 for _, p in self.calls))
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))


for _name in dir(DownstairsComfortTests):
    if _name.startswith('test_') and _name not in CoolingTests.__dict__:
        setattr(CoolingTests, _name, None)
