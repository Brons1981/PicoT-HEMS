from datetime import UTC, datetime

import pytest
from picot_hc.__main__ import Runtime
from test_heating import NOW
from test_heating_local import LocalHeatingFixture


class FloorFixture(LocalHeatingFixture):
    __test__ = False

    def server(self, cls):
        return 'http://ha.invalid'

    def at_time(self, at):
        for zone in self.config['zones']:
            self.states[zone['temperature']]['last_updated'] = datetime.fromtimestamp(
                at, UTC).isoformat()
        return self.poll(at)


@pytest.fixture
def case():
    f = FloorFixture('test_missing_temperature_grace_holds_then_stops')
    f.setUp()
    f.temperature('boven', 22)
    f.temperature('badkamer', 22)
    f.runtime.schedule.data['settings'].update(enabled=True, windows=[
        dict(day=2, start='00:00', end='22:00', target=20, hard=True),
        dict(day=2, start='22:00', end='00:00', target=17, hard=False),
        dict(day=3, start='00:00', end='18:00', target=17, hard=False),
        dict(day=3, start='18:00', end='22:00', target=20, hard=True),
    ])
    f.enable()
    yield f
    f.doCleanups()


def test_22_stops_owned_heat_instead_of_sending_17(case):
    f = case
    f.at_time(NOW+121)
    f.at_time(NOW+152)
    f.temperature('beneden', 19.5)
    plan = f.at_time(NOW+8*3600)
    assert plan['room_floor_mode']
    assert plan['zones']['beneden']['target'] == 17
    assert f.calls[-1][1]['hvac_mode'] == 'off'
    assert not any(c[1].get('temperature') == 17 for c in f.calls)
    assert 'cv' not in plan['desired']


def test_floor_restarts_at_18_and_uses_hysteresis_minimum_runtime(case):
    f = case
    t = NOW+8*3600
    f.temperature('beneden', 17.1)
    f.at_time(t)
    assert not f.calls
    f.temperature('beneden', 16.9)
    f.at_time(t+31)
    assert f.calls[-1][1]['temperature'] == 18
    f.at_time(t+62)
    f.temperature('beneden', 17.4)
    f.at_time(t+120)
    assert len(f.calls) == 1
    f.at_time(t+632)
    assert len(f.calls) == 1
    f.temperature('beneden', 17.5)
    f.at_time(t+643)
    assert f.calls[-1][1]['hvac_mode'] == 'off'
    f.at_time(t+663)
    f.temperature('beneden', 16.9)
    f.at_time(t+694)
    assert len(f.calls) == 2
    f.at_time(t+850)
    assert f.calls[-1][1]['temperature'] == 18


def test_bedroom_waits_for_daytime_price_and_stops_at_noise_window(case):
    f = case
    f.config['bedroom_evening_enabled'] = True
    f.temperature('beneden', 22)
    f.temperature('boven', 15.2)
    prices = f.states[f.config['price_entity']]['attributes']['raw_today']
    prices[:] = [dict(start=datetime.fromtimestamp(start, UTC).isoformat(),
                      end=datetime.fromtimestamp(end, UTC).isoformat(), value=value)
                 for start, end, value in [(NOW-7*3600, NOW+3600, .3),
                                           (NOW+3600, NOW+2*3600, .12),
                                           (NOW+2*3600, NOW+9*3600, .35)]]
    plan = f.at_time(NOW)
    assert not f.calls
    assert '15:00' in plan['zones']['boven']['reason']
    f.at_time(NOW+3600)
    assert f.calls[-1][1]['entity_id'] == f.config['zones'][1]['device']
    assert f.calls[-1][1]['temperature'] == 16.0
    f.at_time(NOW+3631)
    plan = f.at_time(NOW+6*3600)
    assert not plan['demand']['boven']
    assert f.calls[-1][1]['hvac_mode'] == 'off'


def test_bedroom_evening_deadline_works_without_tariff_and_preserves_night_rest(case):
    f = case
    f.config['bedroom_evening_enabled'] = True
    f.temperature('beneden', 22)
    f.temperature('boven', 15.2)
    del f.states[f.config['price_entity']]
    assert not f.at_time(NOW+8*3600)['demand']['boven']
    assert not f.calls
    assert f.at_time(NOW+3*3600+15*60)['demand']['boven']
    assert f.calls[-1][1]['temperature'] == 16.0


def test_bedroom_prefers_hems_solar_window_at_equal_tariff(case):
    f = case
    f.config['bedroom_evening_enabled'] = True
    f.temperature('beneden', 22)
    f.temperature('boven', 15.2)
    def stamp(t):
        return datetime.fromtimestamp(t, UTC).isoformat()

    periods = [(NOW, NOW+3600, 0), (NOW+3600, NOW+7200, 800)]
    slots = [dict(starts_at=stamp(a), ends_at=stamp(b), storage_minimum_wh=500,
                  storage_margin_wh=0, pv_export_wh=solar, grid_import_wh=0, confidence=1)
             for a, b, solar in periods]
    f.states['sensor.picot_energy_outlook'] = dict(state='ready', attributes=dict(
        contract='hems-energy-outlook:v1', status='ready', advisory_only=True,
        approval_required=True, budgets_additive=False, snapshot_id='test',
        generated_at=stamp(NOW), valid_until=stamp(NOW+120), horizon_start=stamp(NOW),
        horizon_end=stamp(NOW+7200), storage_floor_wh=500, projected_minimum_margin_wh=0,
        slots=slots))
    plan = f.at_time(NOW)
    assert not f.calls
    assert '15:00' in plan['zones']['boven']['reason']


def test_manual_heat_below_device_minimum_is_rejected_before_write(case):
    with pytest.raises(ValueError, match='apparaatgrens'):
        case.ctl.submit(case.payload(field='heating', value=17), 120, origin='schedule')
    assert not case.calls


def test_explicit_manual_takeover_is_respected_at_22(case):
    f = case
    f.states[f.config['zones'][0]['device']]['state'] = 'heat'
    f.temperature('beneden', 19)
    f.at_time(NOW+8*3600)
    assert not f.calls


def test_missing_measurement_cannot_start_floor_heat(case):
    case.temperature('beneden', 'unavailable')
    case.at_time(NOW+8*3600)
    assert not case.calls


def test_next_comfort_window_restores_comfort_target(case):
    case.temperature('beneden', 19)
    case.at_time(NOW+8*3600)
    assert not case.calls
    prices = case.states[case.config['price_entity']]['attributes']['raw_today']
    prices[0]['end'] = datetime.fromtimestamp(NOW+48*3600, UTC).isoformat()
    plan = case.at_time(NOW+28*3600)
    assert not plan['room_floor_mode']
    assert case.calls[-1][1]['temperature'] == 20


def test_disable_preempts_floor_minimum_runtime(case):
    t = NOW+8*3600
    case.temperature('beneden', 16.9)
    case.at_time(t)
    case.at_time(t+31)
    case.heat.update(dict(revision=1, settings=dict(case.heat.data['settings'], enabled=False)))
    case.at_time(t+62)
    assert case.calls[-1][1]['hvac_mode'] == 'off'


def test_restart_preserves_floor_cycle_deadline(case):
    t = NOW+8*3600
    case.runtime.schedule.save()
    case.temperature('beneden', 16.9)
    case.at_time(t)
    case.at_time(t+31)
    other = Runtime(case.config, case.store, case.url, 'fake-secret')
    case.runtime, case.heat, case.ctl = other, other.heating, other.control
    case.temperature('beneden', 17.5)
    case.at_time(t+120)
    assert len(case.calls) == 1
    case.at_time(t+601)
    assert case.calls[-1][1]['hvac_mode'] == 'off'
