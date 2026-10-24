"""Route-choice UI boundary: durable backend authority, bounded requests and safe text."""

import json
import shutil
import subprocess
from contextlib import contextmanager
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore, create_web_server


@contextmanager
def server_for(store):
    server = create_web_server(store, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def post(base, payload):
    request = Request(
        base + "/api/route-choice",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_choice_publication_is_copied_and_survives_later_planner_views():
    store = WebViewStore()
    view = {"choices": [{"assignment_id": "today", "status": "selected"}]}
    store.publish_route_choices(view)
    view["choices"][0]["status"] = "released"
    store.publish({"run_id": "one"})
    assert json.loads(store.latest_json())["route_choices"]["choices"][0]["status"] == "selected"
    store.publish({"run_id": "two"})
    assert json.loads(store.latest_json())["route_choices"]["choices"][0]["status"] == "selected"
    store.publish_route_choices({"choices": []})
    assert json.loads(store.latest_json())["route_choices"] == {"choices": []}


def test_choice_callback_runs_outside_store_lock_and_preserves_backend_status():
    store = WebViewStore()
    store.publish({"run_id": "one"})
    seen = []

    def update(payload):
        seen.append(payload)
        view = {"choices": [{"assignment_id": "today", "status": "pending"}]}
        store.publish_route_choices(view)
        return {"status": "pending", "route_choices": view}

    store.set_route_choice_update(update)
    with server_for(store) as base:
        status, result = post(base, {"token": "opaque", "action": "pv"})
        assert status == 200
        assert result["status"] == "pending"
        assert seen == [{"token": "opaque", "action": "pv"}]
        status, _ = post(
            base, {"assignment_id": "today", "action": "release", "request_id": "once"}
        )
        assert status == 200
        assert seen[-1]["assignment_id"] == "today"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"action": "pv"},
        {"action": "pv", "token": ""},
        {"action": "release", "assignment_id": "today"},
        {"action": "delete", "token": "abc"},
    ],
)
def test_malformed_choice_cannot_reach_handler(payload):
    store = WebViewStore()
    seen = []
    store.set_route_choice_update(lambda value: seen.append(value) or {})
    with server_for(store) as base:
        assert post(base, payload)[0] == 400
    assert not seen


def test_unavailable_and_failed_choice_are_not_success():
    store = WebViewStore()
    with server_for(store) as base:
        assert post(base, {"token": "x", "action": "pv"})[0] == 409

        def stale(_):
            raise ValueError("stale plan")

        store.set_route_choice_update(stale)
        assert post(base, {"token": "x", "action": "pv"})[0] == 400

        def disk_failed(_):
            raise OSError("disk unavailable")

        store.set_route_choice_update(disk_failed)
        assert post(base, {"token": "x", "action": "pv"})[0] == 503


def test_choice_js_renders_status_and_actions_without_html_injection():
    node = shutil.which("node")
    assert node, "Node.js required for dashboard behavior check"
    script = DASHBOARD_HTML.split("    let routeChoiceRequestPending = false;", 1)[1]
    script = (
        "let routeChoiceRequestPending = false;"
        + script.split("    function renderUserRules", 1)[0]
    )
    for name in ("comparisonSegments", "comparisonDifferences", "comparisonMode",
                 "appendPlanComparison", "planHistoryTime", "createSvgElement", "appendSvgText"):
        start = DASHBOARD_HTML.index(f"    function {name}(")
        script += DASHBOARD_HTML[start:DASHBOARD_HTML.index("\n    }", start) + 6]
    harness = r"""
class Elem {
  constructor() { this.children = []; this.disabled = false; this.hidden = false; }
  appendChild(child) { this.children.push(child); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  addEventListener(event, callback) { this[event] = callback; }
  querySelectorAll() {
    return this.children.flatMap(c => c.children || []).filter(c => c.type === 'button');
  }
  set innerHTML(_) { throw Error('unsafe HTML'); }
}
const elements = {};
const element = id => elements[id] ||= new Elem();
const document = {createElement: () => new Elem()};
const assert = require('node:assert/strict');
"""
    assertions = r"""
const choice = {status: 'offered', token: 'secret', assignment_id: 'one',
  expires_at: '2999-01-01T00:00:00Z', offer: {alternative: {label: '<img onerror=attack>',
  grid_import_kwh: 1.5, pv_storage_kwh: 3, terminal_soc: 60, acquisition_eur_per_stored_kwh: .3}}};
renderRouteChoices({choices: [choice]});
let card = element('route-choices').children[0];
assert.equal(card.children[0].textContent, 'Alternatief met meer zonnestroom beschikbaar');
assert.ok(card.children.some(c => c.textContent?.includes('<img onerror=attack>')));
assert.deepEqual(card.children.filter(c => c.type === 'button').map(c => c.textContent),
  ['Kies PV-route', 'Behoud automatisch plan']);
renderRouteChoices({choices: [{...choice, offer: {automatic: {label: 'Nacht'}}}]});
assert.deepEqual(element('route-choices').querySelectorAll('button').map(c => c.textContent),
  ['Behoud automatisch plan']);
renderRouteChoices({choices: [{...choice, status: 'selected'}]});
card = element('route-choices').children[0];
assert.equal(card.children[0].textContent, 'PV-route gekozen door gebruiker');
assert.deepEqual(card.children.filter(c => c.type === 'button').map(c => c.textContent),
  ['Laat PicoT weer kiezen']);
renderRouteChoices({choices: [{...choice, expires_at: '2000-01-01T00:00:00Z'}]});
assert.equal(element('route-choices').querySelectorAll('button').length, 0);
renderRouteChoices({choices: [{...choice, status: 'pending'}]});
assert.equal(element('route-choices').querySelectorAll('button').length, 0);
renderRouteChoices({choices: []});
assert.equal(element('route-choice-panel').hidden, true);
"""
    result = subprocess.run(
        [node, "-"], input=harness + script + assertions, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
