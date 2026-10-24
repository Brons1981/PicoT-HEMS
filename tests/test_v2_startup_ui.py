"""Verify startup HTTP and actual dashboard JavaScript behavior."""
import json
import subprocess
from threading import Thread
from urllib.request import urlopen

import pytest

from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore, create_web_server


def _js(action):
    start = DASHBOARD_HTML.index('    // Startup progress reflects')
    end = DASHBOARD_HTML.index('    function flushPendingView()', start)
    harness = r'''
const nodes = {};
const element = id => nodes[id] ??= {
  dataset: {}, attributes: {}, textContent: '',
  style: {removeProperty(key) { delete this[key]; }},
  setAttribute(key, value) {this.attributes[key] = value;},
  removeAttribute(key) {delete this.attributes[key];}
};
let updateWatcherStopped = false, pendingView = null, viewRevision = 0;
const shouldDeferRenderForSelection = () => false;
const refreshLiveStatus = () => {};
const renderView = () => {element('execution-mode').textContent = 'Live uitvoering';};
const setTimeout = callback => {updateWatcherStopped = true; callback();};
'''
    script = (harness + DASHBOARD_HTML[start:end] + '\n(async () => {' + action
              + '\nconsole.log(JSON.stringify(nodes));})();')
    return json.loads(subprocess.run(
        ['node'], input=script, text=True, encoding='utf-8', capture_output=True, check=True,
    ).stdout)


@pytest.mark.parametrize('function', ['loadView', 'watchViewUpdates'])
@pytest.mark.parametrize('body,expected', [
    ('waiting_for_first_run', 'waiting'), ('database_unavailable', 'error'),
])
def test_only_expected_503_is_normal_startup(function, body, expected):
    nodes = _js('''
globalThis.fetch = async () => ({status:503, ok:false, json:async()=>({status:BODY})});
await FUNCTION();
'''.replace('BODY', json.dumps(body)).replace('FUNCTION', function))
    assert nodes['status']['dataset']['state'] == expected
    assert nodes['central-health']['dataset']['health'] == (
        'waiting' if expected == 'waiting' else 'fault'
    )


def test_progress_caps_at_99_and_displays_phase_and_elapsed():
    nodes = _js('renderStartup({state:"ready",percent:100,elapsed_seconds:307});')
    bar = nodes['execution-mode']
    assert bar['attributes']['aria-valuenow'] == '99'
    assert 'Dashboardgegevens weergeven' in bar['textContent']
    assert '5:07' in bar['textContent']
    assert '99%' in bar['style']['background']


def test_successful_view_clears_progress_and_ignores_late_poll():
    nodes = _js('''
renderStartup({state:'starting', label:'Plan berekenen', percent:55, elapsed_seconds:90});
applyView({});
renderStartup({state:'starting', label:'Laat antwoord', percent:20, elapsed_seconds:91});
''')
    bar = nodes['execution-mode']
    assert bar['textContent'] == 'Live uitvoering'
    assert bar['attributes'] == {}
    assert 'background' not in bar['style']
    assert nodes['status']['dataset']['state'] == 'ready'


def test_failed_startup_remains_visible():
    nodes = _js("""
renderStartup({state:'failed',label:'Invoer laden',percent:20,elapsed_seconds:60});
await isWaitingForFirstRun({status:503,json:async()=>({status:'waiting_for_first_run'})});
""")
    assert nodes['central-health']['dataset']['health'] == 'fault'
    assert nodes['status']['dataset']['state'] == 'error'
    assert 'Invoer laden' in nodes['status']['textContent']


def test_startup_endpoint_works_before_first_view():
    store = WebViewStore()
    store.startup_progress.enter('input', 'Gegevens ophalen', 20)
    server = create_web_server(store, host='127.0.0.1', port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/startup', timeout=2) as response:
            body = json.load(response)
            assert response.status == 200
            assert response.headers['Cache-Control'] == 'no-store'
        assert body['phase'] == 'input'
        assert body['percent'] == 20
        assert store.latest_json() is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

