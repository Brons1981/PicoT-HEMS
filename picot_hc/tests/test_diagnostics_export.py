import copy
import gzip
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from picot_hc.__main__ import handler
from picot_hc.control import Control
from picot_hc.core import Store


def runtime(tmp_path):
    config = json.loads((Path(__file__).parents[1] / 'options.example.json').read_text())
    config['tablet_password'] = 'private-password'
    ctl = Control(config, Store(tmp_path / 'hc.sqlite3'), '', 'private-token')
    for i in range(25):
        ctl.save(dict(id=str(i), created=i, status='timed_out', source='beneden',
                      error='Geen bevestiging', field='heating', value=20))
    ctl.states = {'sensor.unrelated_secret': {'state': 'private-state'}}
    return SimpleNamespace(config=config, control=ctl,
        heating=SimpleNamespace(data={'faults': {'beneden': 'Geen bevestiging'}},
                                door_fan=SimpleNamespace(data={'request': None})),
        schedule=SimpleNamespace(data={'overrides': {}}))


def request(rt, *, address='172.30.32.2', tablet=False):
    cls = handler(rt, True, tablet_only=tablet)
    req = cls.__new__(cls)
    req.path = '/api/diagnostics-export'
    req.client_address = (address, 1234)
    req.headers = {}
    req.wfile = io.BytesIO()
    req.send_response = lambda code: setattr(req, 'status', code)
    req.send_error = req.send_response
    req.response_headers = {}
    req.send_header = lambda key, value: req.response_headers.update({key: value})
    req.end_headers = lambda: None
    req.do_GET()
    return req


def test_download_includes_all_stored_commands_and_faults_without_mutating(tmp_path):
    rt = runtime(tmp_path)
    before = copy.deepcopy(rt.heating.data)
    records = rt.control.records()
    response = request(rt)
    assert response.status == 200
    body = gzip.decompress(response.wfile.getvalue())
    data = json.loads(body)
    assert len(data['commands']) == 25
    assert data['commands'] == records
    assert data['heating']['faults']['beneden'] == 'Geen bevestiging'
    assert data['command_timeout_seconds'] == 300
    assert data['hc_version']
    assert rt.heating.data == before and rt.control.records() == records
    assert b'private-' not in body
    assert response.response_headers['Cache-Control'] == 'no-store'
    assert 'attachment;' in response.response_headers['Content-Disposition']
    assert int(response.response_headers['Content-Length']) == len(response.wfile.getvalue())


def test_download_keeps_ingress_and_tablet_access_boundaries(tmp_path):
    rt = runtime(tmp_path)
    assert request(rt, address='192.0.2.1').status == 403
    assert request(rt, tablet=True).status == 401
    with patch('picot_hc.__main__.authorized', return_value=True):
        assert request(rt, tablet=True).status == 404


def test_dashboard_has_relative_download_link():
    html = (Path(__file__).parents[1] / 'picot_hc/web/index.html').read_text()
    assert 'href="api/diagnostics-export"' in html


def test_download_includes_cooling_records_without_mutating(tmp_path):
    rt=runtime(tmp_path)
    samples=[dict(end=123,indoor=20,outdoor=5,coefficient=.01,identity='source')]
    rt.heating.learning=SimpleNamespace(cooling=SimpleNamespace(samples=samples,segment=None))
    response=request(rt)
    data=json.loads(gzip.decompress(response.wfile.getvalue()))
    assert data['learning_models']['cooling']['records']==samples
    assert rt.heating.learning.cooling.samples==samples


def test_export_keeps_decision_timestamp_and_does_not_replan(tmp_path):
    rt = runtime(tmp_path)
    rt.heating.last_decision = {'evaluated_at': 123, 'basis': 'cv_cheaper'}
    rt.heating.data['last_command_decision'] = {'command_id': '24', 'evaluated_at': 120}
    rt.heating.view = lambda *args: (_ for _ in ()).throw(AssertionError('Export must not replan'))
    response = request(rt)
    exported = json.loads(gzip.decompress(response.wfile.getvalue()))
    assert exported['current_decision'] == rt.heating.last_decision
    assert exported['last_command_decision']['command_id'] == '24'
