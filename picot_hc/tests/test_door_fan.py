from unittest.mock import patch

from test_heating_local import LocalHeatingFixture
from test_heating import NOW
from picot_hc.control import DOWNSTAIRS_FAN
from picot_hc.schedule import DOOR


class DoorFanTests(LocalHeatingFixture):
    __test__ = True
    def start_downstairs(self):
        self.temperature('boven', 22)
        self.temperature('badkamer', 22)
        self.states[DOWNSTAIRS_FAN] = dict(entity_id=DOWNSTAIRS_FAN, state='auto',
            attributes={'options': ['auto', 'stil', 'laag', 'midden', 'hoog']})
        self.enable()
        self.poll(NOW+121)
        self.poll(NOW+152)

    def test_fan_open_quiet_closed_auto_without_compressor_stop(self):
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.assertEqual(len(self.calls), 1)
        self.poll(NOW+250)
        self.assertEqual(self.calls[-1], ('/api/services/select/select_option',
            {'entity_id': DOWNSTAIRS_FAN, 'option': 'stil'}))
        self.poll(NOW+281)
        self.poll(NOW+312)
        self.assertEqual(len(self.calls), 2)
        self.states[DOOR]['state'] = 'off'
        self.poll(NOW+340)
        self.assertEqual(len(self.calls), 2)
        self.poll(NOW+470)
        self.assertEqual(self.calls[-1][1], {'entity_id': DOWNSTAIRS_FAN, 'option': 'auto'})
        self.poll(NOW+501)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(any(data.get('hvac_mode') == 'off' for _, data in self.calls))
        self.assertEqual(self.runtime.schedule.view(self.at)['overrides'], [])

    def test_fan_missing_select_does_not_turn_airco_off(self):
        self.start_downstairs()
        del self.states[DOWNSTAIRS_FAN]
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.assertEqual(len(self.calls), 1)

    def test_fan_no_write_during_data_gap_or_manual_takeover(self):
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.temperature('beneden', 'unavailable')
        self.poll(NOW+250)
        self.assertEqual(len(self.calls), 1)
        self.temperature('beneden', 18)
        self.states[self.config['zones'][0]['device']]['attributes']['temperature'] = 23
        self.poll(NOW+281)
        self.assertEqual(len(self.calls), 1)

    def test_fan_fresh_read_door_race_prevents_quiet_command(self):
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        import copy
        def race(*args):
            self.states[DOOR]['state'] = 'off'
            return copy.deepcopy(self.states)
        with patch('picot_hc.control.fetch_states', side_effect=race):
            self.poll(NOW+250)
        self.assertEqual(len(self.calls), 1)

    def test_fan_unconfirmed_command_is_not_replayed(self):
        self.start_downstairs()
        self.apply = False
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.poll(NOW+281)
        self.poll(NOW+600)
        self.assertEqual(len(self.calls), 2)

    def test_fan_never_starts_airco_for_open_door(self):
        self.temperature('boven', 22)
        self.temperature('badkamer', 22)
        self.config['gas_valid_until'] = '2020-01-01'
        self.states[DOOR]['state'] = 'on'
        self.enable()
        self.poll(NOW+121)
        self.assertEqual(self.calls, [])

    def test_fan_storage_failure_does_not_dispatch_or_block_next_attempt(self):
        import sqlite3
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        with patch.object(self.heat.door_fan, 'save', side_effect=sqlite3.Error('full')):
            with self.assertRaises(sqlite3.Error):
                self.poll(NOW+250)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(self.heat.door_fan.data['request'])
        self.poll(NOW+281)
        self.assertEqual(self.calls[-1][1], {'entity_id': DOWNSTAIRS_FAN, 'option': 'stil'})
        self.assertEqual(len(self.calls), 2)

    def test_fan_resume_manual_off_cannot_start_with_open_door(self):
        self.start_downstairs()
        self.config['gas_valid_until'] = '2020-01-01'
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.poll(NOW+281)
        self.states[self.config['zones'][0]['device']]['state'] = 'off'
        self.poll(NOW+400)
        self.runtime.schedule.resume(NOW+450)
        self.poll(NOW+480)
        self.assertFalse(any(data.get('hvac_mode') == 'heat' for _, data in self.calls[2:]))
        self.assertEqual(self.states[self.config['zones'][0]['device']]['state'], 'off')
        self.states[DOOR]['state'] = 'off'
        self.poll(NOW+500)
        self.assertFalse(any(data.get('hvac_mode') == 'heat' for _, data in self.calls[2:]))
        self.poll(NOW+700)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'heat')

    def test_fan_restart_keeps_quiet_ownership_and_restores_auto(self):
        from picot_hc.heating import Heating
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.poll(NOW+281)
        self.heat = Heating(self.ctl, self.runtime.schedule, self.store)
        self.poll(NOW+312)
        self.assertEqual(len(self.calls), 2)
        self.states[DOOR]['state'] = 'off'
        self.poll(NOW+340)
        self.poll(NOW+470)
        self.assertEqual(self.calls[-1][1], {'entity_id': DOWNSTAIRS_FAN, 'option': 'auto'})

    def test_fan_explicit_disable_still_stops_heat_with_open_door(self):
        self.start_downstairs()
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.poll(NOW+281)
        self.heat.update(dict(revision=self.heat.data['revision'],
            settings=dict(self.heat.data['settings'], enabled=False)))
        self.poll(NOW+312)
        self.assertEqual(self.calls[-1][1]['hvac_mode'], 'off')

    def test_fan_unsupported_option_is_not_sent(self):
        self.start_downstairs()
        self.states[DOWNSTAIRS_FAN]['attributes']['options'] = ['auto', 'hoog']
        self.states[DOOR]['state'] = 'on'
        self.poll(NOW+180)
        self.poll(NOW+250)
        self.assertEqual(len(self.calls), 1)


for _name in dir(LocalHeatingFixture):
    if _name.startswith('test_') and _name not in DoorFanTests.__dict__:
        setattr(DoorFanTests, _name, None)
