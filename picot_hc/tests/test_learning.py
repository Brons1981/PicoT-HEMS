"""Adaptive start deadlines through real schedule, heating and SQLite."""
from test_downstairs_comfort import DownstairsComfortTests, NOW


class LearningTests(DownstairsComfortTests):
    # Reuse the transport fixture, not its inherited test suite.
    def configure(self):
        self.settings(enabled=True, learning_enabled=True, initial_preheat_minutes=45,
            max_preheat_minutes=180, setback_temperature=17,
            windows=[dict(day=3, start='19:00', end='22:00', target=20, hard=True)])
        self.temperature('beneden', 18)

    def test_preheat_only_downstairs_and_maintains_at_target(self):
        self.configure()
        self.assertEqual(self.poll(600)['zones']['beneden']['target'], 17)
        plan = self.poll(300)
        self.assertEqual(plan['zones']['beneden']['target'], 20)
        self.assertTrue(plan['preheating'])
        self.assertFalse(plan['zones']['boven']['demand'])
        self.temperature('beneden', 20)
        self.poll()
        self.assertTrue(self.poll()['zones']['beneden']['demand'])
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))

    def test_missed_deadline_extends_next_start_and_persists(self):
        self.configure()
        self.poll(900)
        while self.now < NOW+3600:
            self.poll(min(60, NOW+3600-self.now))
        status = self.heat.view(self.config, self.now)['learning_status']
        self.assertEqual(status['lead_minutes'], 60)
        self.assertEqual(status['outcomes'][-1]['result'], 'late')
        from picot_hc.learning import Learning
        restored = Learning(self.store)
        self.assertEqual(restored.status(self.schedule.view(self.now))['lead_minutes'], 60)

    def test_disabled_schedule_has_no_preheat(self):
        self.configure()
        self.settings(enabled=False, thermostat_temperature=19)
        plan = self.poll(1000)
        self.assertEqual(plan['zones']['beneden']['target'], 19)
        self.assertFalse(plan['preheating'])

    def test_gap_or_open_door_discards_learning(self):
        from picot_hc.schedule import DOOR
        self.configure()
        self.poll(900)
        self.states[DOOR]['state'] = 'on'
        self.poll(60)
        self.states[DOOR]['state'] = 'off'
        self.poll(2640)
        self.assertEqual(self.heat.view(self.config, self.now)['learning_status']['outcomes'], [])

    def test_early_arrival_reduces_lead_but_keeps_heating(self):
        self.configure()
        self.poll(900)
        while self.now < NOW+1800:
            self.poll(60)
        self.temperature('beneden', 20)
        while self.now < NOW+3600:
            self.poll(60)
        status = self.heat.view(self.config, self.now)['learning_status']
        self.assertEqual(status['lead_minutes'], 40)
        self.assertEqual(status['outcomes'][-1]['result'], 'early')
        self.assertFalse(any(p.get('hvac_mode') == 'off' for _, p in self.calls))

    def test_limits_validation_and_learning_opt_in(self):
        with self.assertRaises(ValueError):
            self.settings(initial_preheat_minutes=90, max_preheat_minutes=45)
        with self.assertRaises(ValueError):
            self.settings(learning_enabled=1)
        self.configure()
        self.settings(learning_enabled=False)
        self.assertEqual(self.poll(900)['zones']['beneden']['target'], 17)
        self.assertFalse(self.heat.view(self.config, self.now)['learning'])

    def test_manual_hold_and_missing_temperature_block_preheat(self):
        self.configure()
        self.schedule.hold('beneden', 'mode', 'off', self.now, 'test')
        plan = self.poll(900)
        self.assertNotIn('beneden', plan['desired'])
        self.assertNotIn('cv', plan['desired'])
        self.assertIsNone(self.heat.learning.session)
        self.schedule.resume(self.now)
        self.temperature('beneden', 'unavailable')
        plan = self.poll()
        self.assertNotIn('beneden', plan['desired'])
        self.assertIsNone(self.heat.learning.session)

    def test_missed_deadline_respects_maximum(self):
        self.configure()
        self.settings(max_preheat_minutes=45)
        self.poll(900)
        while self.now < NOW+3600:
            self.poll(60)
        self.assertEqual(self.heat.view(self.config, self.now)['learning_status']['lead_minutes'], 45)

    def test_learning_never_overrides_existing_comfort_window(self):
        self.configure()
        self.settings(windows=[dict(day=3, start='18:00', end='19:00', target=19, hard=True),
                               dict(day=3, start='19:00', end='22:00', target=20, hard=True)])
        plan = self.poll(900)
        self.assertEqual(plan['zones']['beneden']['target'], 19)
        self.assertFalse(plan['preheating'])


# Keep only new cases; inherited tests run separately in their original class.
for _name in dir(DownstairsComfortTests):
    if _name.startswith('test_') and _name not in LearningTests.__dict__:
        setattr(LearningTests, _name, None)
