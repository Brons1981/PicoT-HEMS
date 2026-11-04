"""In-process HA boundary for targeted controller tests where sockets are unavailable."""
import copy
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

import test_heating


class LocalHeatingFixture(test_heating.HeatingTests):
    __test__ = False
    def setUp(self):
        super().setUp()

        def states(*args, **kwargs):
            if self.read_fail:
                raise OSError('HA unavailable')
            return copy.deepcopy(self.states)

        def request(url, token, path, payload=None):
            if self.read_fail:
                raise OSError('HA unavailable')
            if path == '/config':
                return {'unit_system': {'temperature': self.unit}}
            if path.startswith('/services/'):
                self.calls.append(('/api' + path, copy.deepcopy(payload)))
                if self.apply:
                    state = self.states[payload['entity_id']]
                    if 'hvac_mode' in payload:
                        state['state'] = payload['hvac_mode']
                    if 'temperature' in payload:
                        state['attributes']['temperature'] = payload['temperature']
                    if 'option' in payload:
                        state['state'] = payload['option']
                    if path.startswith('/services/switch/'):
                        state['state'] = 'on' if path.endswith('turn_on') else 'off'
                if self.drop:
                    raise OSError('Reply lost')
                if self.status >= 400:
                    raise HTTPError(url, self.status, 'HA response', {}, None)
                return []
            raise AssertionError('Unexpected HA request: ' + path)

        for target, replacement in [('picot_hc.control.fetch_states', states),
                                    ('picot_hc.control.ha_request', request)]:
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)


def load_tests(loader, tests, pattern):
    names = (
        'test_temporary_missing_price_holds_existing_airco',
        'test_grace_deadline_survives_hc_restart',
        'test_missing_temperature_does_not_authorize_airco_start',
        'test_missing_temperature_grace_holds_then_stops',
        'test_data_recovery_during_grace_does_not_cycle_or_write_target',
        'test_missing_door_grace_and_explicit_disable',
        'test_restart_preserves_enabled_and_confirmed_heat_without_replay',
    )
    return unittest.TestSuite(LocalHeatingFixture(name) for name in names)
