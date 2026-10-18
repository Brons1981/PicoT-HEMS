"""Exercise HTTP handlers without requiring sandbox loopback socket access."""

import json
import shutil
import subprocess
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from picot.v2 import web_ui as hems
from picot_energy_devices import web_ui as devices


@pytest.mark.parametrize("module", [hems, devices])
def test_export_acknowledges_before_build_finishes_and_downloads_exact_job(module, monkeypatch):
    entered, release = Event(), Event()

    def build(*args, progress):
        progress(1, 3, "Bestanden verzamelen")
        entered.set()
        assert release.wait(3)
        progress(3, 3, "Gereed")
        return b"zip-content"

    server = Mock(side_effect=lambda address, handler: handler)
    monkeypatch.setattr(module, "ThreadingHTTPServer", server)
    if module is hems:
        monkeypatch.setattr(module, "diagnostic_zip", build)
        handler_type = module.create_web_server(hems.WebViewStore(), host="", port=0)
    else:
        handler_type = module.create_web_server(
            Mock(), host="", port=0, diagnostics=SimpleNamespace(export_zip=build),
        )

    def request(method, path):
        handler = object.__new__(handler_type)
        handler.path = path
        handler.wfile = BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        getattr(handler, f"do_{method}")()
        return handler.send_response.call_args.args[0], handler.wfile.getvalue(), handler

    try:
        status, body, _ = request("POST", "/api/diagnostics/export")
        assert status == 202
        job = json.loads(body)
        assert job["status"] == "building"
        assert entered.wait(2)
        _, duplicate, _ = request("POST", "/api/diagnostics/export")
        assert json.loads(duplicate)["job_id"] == job["job_id"]
        _, body, _ = request("GET", "/api/diagnostics/export")
        assert json.loads(body)["completed"] == 1
        assert request("GET", "/api/diagnostics/export/download?job_id=wrong")[0] == 404
    finally:
        release.set()
    # The worker is tiny; polling through the endpoint verifies its published state.
    from time import monotonic, sleep

    deadline = monotonic() + 2
    while monotonic() < deadline:
        _, body, _ = request("GET", "/api/diagnostics/export")
        if json.loads(body)["status"] == "ready":
            break
        sleep(0.001)
    assert json.loads(body)["status"] == "ready"
    status, body, handler = request(
        "GET", f'/api/diagnostics/export/download?job_id={job["job_id"]}',
    )
    assert status == 200
    assert body == b"zip-content"
    handler.send_header.assert_any_call("Content-Length", str(len(body)))
    assert request("GET", "/api/diagnostics/export/download?job_id=wrong")[0] == 404


def test_missing_energy_diagnostics_is_reported(monkeypatch):
    monkeypatch.setattr(devices, "ThreadingHTTPServer", lambda address, handler: handler)
    handler_type = devices.create_web_server(Mock(), host="", port=0)
    handler = object.__new__(handler_type)
    handler.path = "/api/diagnostics/export"
    handler._json = Mock()
    handler.do_POST()
    assert handler._json.call_args.args[0] == 503


@pytest.mark.parametrize(
    "html", [hems.DASHBOARD_HTML, devices.DASHBOARD_HTML], ids=["hems", "devices"],
)
def test_dashboard_reports_acknowledgement_build_transfer_and_failure(html):
    assert 'id="diagnostic-export-progress"' in html
    assert "nog geen ontvangstbevestiging" in html
    assert "Opdracht ontvangen door PicoT" in html
    assert "job.completed" in html and "job.total" in html
    assert "response.body.getReader()" in html
    assert "Controleer je downloads" in html
    assert "Probeer opnieuw" in html
    assert 'request("api/diagnostics/export"' in html
    assert 'button.disabled = true' in html
    assert 'button.disabled = false' in html


@pytest.mark.parametrize("module", [hems, devices], ids=["hems", "devices"])
@pytest.mark.parametrize("fail", [False, True], ids=["success", "failure"])
def test_browser_export_lifecycle(module, fail):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute dashboard JavaScript")
    html = module.DASHBOARD_HTML
    start = html.index(
        '    (() => {\n      const button = document.getElementById("diagnostic-export")',
    )
    script = html[start:html.index("    })();", start) + len("    })();")]
    harness = r'''
const assert = require("node:assert/strict");
const messages = [];
const button = {disabled:false, addEventListener:(_, callback) => button.click = callback};
const status = {set textContent(value) { this.value = value; messages.push(value); },
                get textContent() { return this.value; }};
const progress = {removeAttribute(name) { delete this[name]; }};
let saved = 0;
global.document = {
  getElementById:id => ({"diagnostic-export":button, "diagnostic-export-status":status,
                         "diagnostic-export-progress":progress})[id],
  createElement:() => ({click:() => saved++, remove:() => {}}),
  body:{appendChild:() => {}}
};
global.setTimeout = (callback, delay) => { if (delay === 1000) callback(); return 1; };
global.clearTimeout = () => {};
global.URL = {createObjectURL:() => "blob:test", revokeObjectURL:() => {}};
let call = 0;
global.fetch = async (url, options) => {
  call++;
  if (call === 1) {
    assert.equal(button.disabled, true);
    assert.match(status.value, /nog geen ontvangstbevestiging/);
    assert.equal(options.method, "POST");
    return {ok:true,json:async () => ({status:"building",job_id:"job",total:4,completed:1,
                                      message:"Verzamelen"})};
  }
  if (call === 2) {
    assert.match(status.value, /Opdracht ontvangen/);
    assert.match(status.value, /25%/);
    assert.equal(progress.value, 1);
    return {ok:true,json:async () => ({status:"ready",job_id:"job",size_bytes:4,
                                      filename:"diagnostics.zip"})};
  }
  assert.match(url, /download\?job_id=job/);
  let chunk = 0;
  return {ok:true, headers:{get:() => "4"}, body:{getReader:() => ({read:async () => {
    if (FAIL) throw new Error("verbinding verbroken");
    if (chunk++ === 0) return {done:false,value:new Uint8Array([1,2])};
    if (chunk === 2) {
      assert.match(status.value, /Downloaden:/);
      assert.equal(progress.value, 2);
      return {done:false,value:new Uint8Array([3,4])};
    }
    return {done:true};
  }})}};
};
'''.replace("FAIL", json.dumps(fail))
    checks = '''
button.click().then(() => {
  assert.equal(button.disabled, false);
  if (FAIL) {
    assert.equal(saved, 0);
    assert.match(status.value, /verbinding verbroken.*Probeer opnieuw/);
    assert.equal(progress.hidden, true);
  } else {
    assert.equal(saved, 1);
    assert.match(status.value, /aan de browser aangeboden/);
    assert.equal(progress.value, progress.max);
  }
}).catch(error => { console.error(error); process.exitCode = 1; });
'''.replace("FAIL", json.dumps(fail))
    result = subprocess.run(
        [node, "-e", harness + script + checks], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
