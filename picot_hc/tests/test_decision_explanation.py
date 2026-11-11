"""Decision evidence with real control/SQLite and an in-process HA boundary."""
import copy
from unittest.mock import patch

import test_heating
from test_heating_local import LocalHeatingFixture
from picot_hc.diagnostics import collect


NOW = test_heating.NOW


class DecisionExplanationTests(LocalHeatingFixture):
    __test__ = True
    def server(self, cls):
        return 'http://ha.invalid'

    # Reuse the real fixture without re-running the inherited test suite.
    def test_expensive_power_explains_cv_and_records_command_basis(self):
        self.price(.679)
        self.temperature('boven', 22)
        self.temperature('badkamer', 22)
        self.config.update(gas_price=1.42, gas_valid_until='2027-01-01')
        self.enable()
        view = self.poll(NOW+121)
        decision = view['decision']
        self.assertEqual(decision['basis'], 'cv_cheaper')
        self.assertEqual(decision['selected'], ['cv'])
        self.assertAlmostEqual(decision['costs']['beneden'], .679/3.72)
        self.assertAlmostEqual(decision['prices']['gas_eur_m3'], 1.42)
        with patch('time.time', return_value=NOW+121):
            exported = collect(self.runtime)
        self.assertEqual(exported['last_command_decision']['basis'], 'cv_cheaper')
        self.assertEqual(exported['last_command_decision']['prices']['electricity_eur_kwh'], .679)
        self.assertIn('current_temperature', exported['reported_states'][self.config['cv']]['attributes'])

    def test_faulted_cv_retains_cost_and_separates_choice_from_execution(self):
        self.price(.25)
        self.temperature('boven', 22)
        self.temperature('badkamer', 22)
        self.enable()
        self.heat.data['faults']['cv'] = 'CV ruststand niet bevestigd'
        self.heat.data['owned']['cv'] = dict(command='missing', since=NOW, standby=True)
        with patch('time.time', return_value=NOW+121):
            self.ctl.observe(self.states, NOW+121, NOW+121)
            view = self.heat.view(self.config, NOW+121)
        # A missing command record cannot prove the CV request has finished.
        self.assertEqual(view['decision']['selected'], [])
        self.assertEqual(view['decision']['basis'], 'blocked')
        self.assertIn('CV ruststand niet bevestigd', view['decision']['candidates']['cv']['reason'])
        self.assertEqual(view['decision']['execution']['beneden']['conflicts'], ['cv'])
        self.assertEqual(view['decision']['execution']['beneden']['mode'], 'off')

    def test_temperatures_missing_prices_and_read_only_export(self):
        self.enable()
        self.temperature('beneden', 17.3)
        self.states[self.config['cv']]['attributes']['current_temperature'] = 19
        self.states[self.config['price_entity']]['state'] = 'unavailable'
        self.config['gas_valid_until'] = '2020-01-01'
        with patch('time.time', return_value=NOW+121):
            self.ctl.observe(self.states, NOW+121, NOW+121)
            before = copy.deepcopy(self.calls)
            decision = self.heat.view(self.config, NOW+121)['decision']
            exported = collect(self.runtime)
        self.assertIsNone(decision['prices']['electricity_eur_kwh'])
        self.assertFalse(decision['prices']['gas_valid'])
        self.assertTrue(decision['prices']['warnings'])
        self.assertAlmostEqual(decision['temperature_difference_c'], 1.7)
        self.assertEqual(decision['thermostat_temperature_c'], 19)
        self.assertEqual(exported['current_decision']['room_temperature_c'], 17.3)
        self.assertEqual(self.calls, before)

    def test_price_boundaries_and_unusable_gas_keep_their_actual_reason(self):
        self.config.update(gas_price=1.42, gas_valid_until='2027-01-01')
        self.enable()
        for price, valid_until, expected in [
                (0, '2027-01-01', 'airco_preferred'),
                (-.1, '2027-01-01', 'airco_preferred'),
                (.679, '2020-01-01', 'airco_available')]:
            with self.subTest(price=price, valid_until=valid_until), patch('time.time', return_value=NOW+121):
                self.price(price)
                self.config['gas_valid_until'] = valid_until
                self.ctl.observe(self.states, NOW+121, NOW+121)
                d = self.heat.view(self.config, NOW+121)['decision']
                self.assertEqual(d['basis'], expected)
                self.assertEqual(d['selected'], ['beneden'])
                self.assertEqual(d['prices']['electricity_eur_kwh'], price)
        self.assertEqual(self.calls, [])

    def test_minimum_run_is_not_described_as_cheapest_source(self):
        self.temperature('boven', 22)
        self.temperature('badkamer', 22)
        self.config.update(gas_price=1.42, gas_valid_until='2027-01-01')
        self.enable()
        self.poll(NOW+121)
        self.poll(NOW+152)
        self.price(.9)
        d = self.poll(NOW+180)['decision']
        self.assertEqual(d['basis'], 'minimum_run')
        self.assertEqual(d['selected'], ['beneden'])
        self.assertLess(d['costs']['cv'], d['costs']['beneden'])


# unittest inherits methods; keep only the focused scenarios in this subclass.
for _name in dir(test_heating.HeatingTests):
    if _name.startswith('test_') and _name not in DecisionExplanationTests.__dict__:
        setattr(DecisionExplanationTests, _name, None)
