import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch

from picot_hc.__main__ import Runtime
from picot_hc.core import Store


def runtime(tmp_path):
    config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
    with patch('picot_hc.__main__.HealthNotifier') as notifier:
        rt = Runtime(config, Store(tmp_path / 'hc.sqlite3'), '', '')
    return rt, notifier.return_value


def test_connection_failure_and_recovery_are_observed_without_dashboard(tmp_path):
    rt, notifier = runtime(tmp_path)
    with patch('picot_hc.__main__.fetch_states', side_effect=OSError):
        rt.collect()
    assert rt.connection == 'disconnected'
    assert notifier.observe.call_args_list[0].args[:2] == ('ha_connection', True)
    notifier.reset_mock()
    with patch('picot_hc.__main__.fetch_states', return_value={}):
        rt.collect()
    assert rt.connection == 'connected'
    assert notifier.observe.call_args_list[0].args[:2] == ('ha_connection', False)


def test_heating_fault_and_reset_reported_without_control_change(tmp_path):
    rt, notifier = runtime(tmp_path)
    rt.heating.data['faults']['cv'] = 'Geen bevestiging.'
    before = copy.deepcopy(rt.heating.data)
    rt._notify_health()
    assert any(c.args[:2] == ('heating_cv', True) for c in notifier.observe.call_args_list)
    assert rt.heating.data == before
    notifier.reset_mock()
    rt.heating.data['faults'].clear()
    rt._notify_health()
    assert any(c.args[:2] == ('heating_cv', False) for c in notifier.observe.call_args_list)


def test_command_fault_and_confirmation_and_reporting_failure_do_not_change_command(tmp_path):
    rt, notifier = runtime(tmp_path)
    command = dict(id='test-command-12345', created=1, source='cv', status='timed_out', error='Geen bevestiging.')
    rt.control.save(command)
    assert notifier.observe.call_args.args[:2] == ('command_cv', True)
    command.update(status='confirmed', error=None)
    rt.control.save(command)
    assert notifier.observe.call_args.args[:2] == ('command_cv', False)
    notifier.observe = Mock(side_effect=OSError)
    rt.control.save(command)
    assert rt.control.records() == [command]
    rt._notify_health()


def test_notification_options_are_forwarded(tmp_path):
    config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
    config.update(health_notifications_enabled=False, health_notifications_recovery_enabled=False)
    with patch('picot_hc.__main__.HealthNotifier') as notifier:
        Runtime(config, Store(tmp_path / 'hc.sqlite3'), '', '')
    assert notifier.call_args.kwargs == {'enabled': False, 'recovery_enabled': False}


def test_vendored_notifier_matches_shared_source():
    root = Path(__file__).resolve().parents[2]
    assert (root / 'picot_hc/picot_hc/health_notifications.py').read_bytes() == (
        root / 'src/picot/health_notifications.py').read_bytes()
