"""ROOM temperature contract: persistence, boundaries and regulator precedence."""
import copy
import unittest
from unittest.mock import patch

import test_downstairs_comfort as fixture
from picot_hc.schedule import Schedule

NOW = fixture.NOW

class TabletTemperatureTests(unittest.TestCase):
    setUp = fixture.DownstairsComfortTests.setUp
    stamp = staticmethod(fixture.DownstairsComfortTests.stamp)
    request = fixture.DownstairsComfortTests.request
    settings = fixture.DownstairsComfortTests.settings
    temperature = fixture.DownstairsComfortTests.temperature

    def enable_schedule(self):
        self.settings(enabled=True, setback_temperature=16, windows=[
            dict(day=3, start='18:00', end='19:00', target=20, hard=False),
            dict(day=3, start='19:00', end='20:00', target=20, hard=False)])

    def set_target(self, target=22.5):
        return self.schedule.set_temperature(dict(revision=self.schedule.data['revision'], temperature=target), NOW)

    def test_boundary_equal_targets_and_restart(self):
        self.enable_schedule()
        revision = self.schedule.data['revision']
        view = self.set_target()
        self.assertEqual(view['revision'], revision+1)
        self.assertEqual(view['temporary_temperature'], dict(temperature=22.5, since=NOW, until=NOW+3600))
        self.assertEqual(view['overrides'], [])
        self.assertEqual(view['comfort']['zones']['beneden']['bounds'], dict(minimum=22.5, maximum=22.5))
        restored = Schedule(self.ctl, self.store, self.config)
        self.assertEqual(restored.view(NOW+3599)['comfort']['zones']['beneden']['request']['target'], 22.5)
        # Seven elapsed days crosses autumn DST and lands at 17:00 (setback).
        for moment, target in ((NOW+3600, 20), (NOW+3601, 20), (NOW+7*86400, 16)):
            view = restored.view(moment)
            self.assertIsNone(view['temporary_temperature'])
            self.assertEqual(view['comfort']['zones']['beneden']['request']['target'], target)
        restored.tick(self.config, NOW+3600)
        self.assertIsNone(restored.data['temporary_temperature'])
        self.assertEqual(self.calls, [])

    def test_disabled_is_persistent_thermostat(self):
        view = self.set_target(19.5)
        self.assertIsNone(view['temporary_temperature'])
        self.assertEqual(view['settings']['thermostat_temperature'], 19.5)
        restored = Schedule(self.ctl, self.store, self.config)
        self.assertEqual(restored.view(NOW+86400*8)['comfort']['zones']['beneden']['request']['target'], 19.5)

    def test_validation_and_revision_leave_state_unchanged(self):
        self.enable_schedule()
        before = copy.deepcopy(self.schedule.data)
        rev = before['revision']
        payloads = [None, {}, {'revision': rev}, {'revision': rev, 'temperature': 20, 'extra': 1}]
        payloads += [dict(revision=rev, temperature=t) for t in (True, False, None, '20', 4.5, 35.5, 20.25, float('nan'), float('inf'), -float('inf'), 10**1000)]
        payloads += [dict(revision=r, temperature=20) for r in (rev-1, rev+1, True, float(rev), str(rev))]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.schedule.set_temperature(payload, NOW)
                self.assertEqual(self.schedule.data, before)
        for target in (5, 5.5, 34.5, 35):
            self.assertEqual(self.set_target(target)['temporary_temperature']['temperature'], target)
        with self.assertRaises(ValueError):
            self.schedule.set_temperature(dict(revision=rev, temperature=20), NOW)

    def test_settings_changes_and_resume_clear_override(self):
        self.enable_schedule()
        self.set_target()
        self.settings(optimization_band=.5)
        self.assertIsNone(self.schedule.view(NOW)['temporary_temperature'])
        self.set_target()
        self.settings(enabled=False)
        self.assertIsNone(self.schedule.view(NOW)['temporary_temperature'])
        self.assertEqual(self.schedule.view(NOW)['settings']['thermostat_temperature'], 20)
        self.enable_schedule()
        self.set_target()
        self.schedule.hold('cv', 'mode', 'off', NOW, 'manual')
        view = self.schedule.resume(NOW)
        self.assertIsNone(view['temporary_temperature'])
        self.assertEqual(view['overrides'], [])

    def test_storage_failure_rolls_back(self):
        self.enable_schedule()
        before = copy.deepcopy(self.schedule.data)
        with patch.object(self.schedule, 'save', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.set_target()
        self.assertEqual(self.schedule.data, before)

    def test_room_resume_preserves_source_holds_and_legacy_pause(self):
        self.enable_schedule()
        self.set_target()
        self.schedule.hold('cv', 'mode', 'off', NOW, 'manual')
        self.schedule.data['legacy_pause'] = dict(until=NOW+1800)
        before = copy.deepcopy(self.schedule.data)
        view = self.schedule.resume_temperature(NOW)
        self.assertIsNone(view['temporary_temperature'])
        self.assertEqual(view['revision'], before['revision']+1)
        self.assertEqual(self.schedule.data['overrides'], before['overrides'])
        self.assertEqual(view['legacy_pause'], before['legacy_pause'])
        restored = Schedule(self.ctl, self.store, self.config)
        self.assertIsNone(restored.view(NOW)['temporary_temperature'])
        self.assertEqual(restored.data['overrides'], before['overrides'])
        before = copy.deepcopy(self.schedule.data)
        with patch.object(self.schedule, 'save', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.schedule.resume_temperature(NOW)
        self.assertEqual(self.schedule.data, before)

    def test_next_start_in_gap(self):
        self.settings(enabled=True, setback_temperature=16, windows=[
            dict(day=3, start='19:00', end='20:00', target=20, hard=True)])
        self.assertEqual(self.set_target()['temporary_temperature']['until'], NOW+3600)
        self.assertEqual(self.schedule.view(NOW+3600)['comfort']['zones']['beneden']['request']['target'], 20)

    def test_learning_cannot_override_and_source_hold_still_wins(self):
        self.enable_schedule()
        self.set_target(23)
        for phase, target in [('preheat', 25), ('coast', 19), ('setback', 21)]:
            with self.subTest(phase=phase), patch.object(self.heat.learning, 'recommendation', return_value=dict(
                    target=target, phase=phase, preheating=phase=='preheat', enabled=True)):
                plan = self.heat.plan(self.config, NOW)
                self.assertEqual(plan['zones']['beneden']['target'], 23)
                self.assertFalse(plan['preheating'])
        self.schedule.hold('cv', 'mode', 'off', NOW, 'manual')
        plan = self.heat.plan(self.config, NOW)
        self.assertEqual(plan['zones']['beneden']['target'], 23)
        self.assertFalse(plan['zones']['beneden']['demand'])
        self.assertNotIn('cv', plan['desired'])
        self.assertNotIn('beneden', plan['desired'])

    def test_stale_sensor_still_blocks(self):
        self.enable_schedule()
        self.set_target(23)
        plan = self.heat.plan(self.config, NOW+901)
        self.assertFalse(plan['zones']['beneden']['demand'])
        self.assertNotIn('beneden', plan['desired'])
        self.assertNotIn('cv', plan['desired'])

    def test_scheduled_energy_recipe_cannot_replace_temporary_target(self):
        self.enable_schedule()
        self.set_target(23)
        with patch.object(self.heat.energy_start, 'apply', side_effect=AssertionError('scheduled recipe applied')):
            plan = self.heat.plan(self.config, NOW)
        self.assertEqual(plan['zones']['beneden']['target'], 23)
        self.assertFalse(plan['preheating'])
        self.schedule.resume_temperature(NOW)
        with patch.object(self.heat.energy_start, 'apply', side_effect=lambda plan, *args: plan) as apply:
            self.heat.plan(self.config, NOW)
        apply.assert_called_once()
