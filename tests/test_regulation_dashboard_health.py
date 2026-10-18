"""Warnings remain visible when calculated values exist but control is blocked."""

import shutil
import subprocess
from datetime import UTC, datetime, timedelta

from picot.v2.web_ui import DASHBOARD_HTML as HEMS_HTML
from picot_energy_devices.regulation import RegulationSnapshotStore
from picot_energy_devices.web_ui import DASHBOARD_HTML


def test_health_view_preserves_blocked_evidence_and_marks_stale() -> None:
    now = datetime(2026, 10, 18, 5, 0, tzinfo=UTC)
    store = RegulationSnapshotStore(control_enabled=True)
    store.update({"status": "blocked", "reason": "persistent_measurement_loss",
                  "evaluated_at": now.isoformat(), "raw_grid_w": 2500,
                  "intended_candidate_w": 200, "offered_p1_w": 2500,
                  "latched_at": now.isoformat()})
    view = store.view(now=now)
    assert view["status"] == "blocked"
    assert view["offered_p1_w"] == 2500
    assert view["intended_candidate_w"] == 200
    view["status"] = "ready"
    assert store.view(now=now)["status"] == "blocked"
    assert store.read(now=now) is None
    stale = store.view(now=now + timedelta(seconds=4))
    assert stale["status"] == "unavailable"
    assert stale["latched_at"] == now.isoformat()


def test_regulation_warning_covers_blocked_recovering_and_clear() -> None:
    node = shutil.which("node")
    assert node is not None
    render = DASHBOARD_HTML.split("    function renderRegulation(value) {")[1].split(
        "    async function load() {")[0]
    script = """
const assert = require('node:assert/strict');
const elements = {};
const el = id => elements[id] ??= {classList:{toggle(){}}, textContent:'', hidden:false};
const number = (value, suffix) => `${value} ${suffix}`;
function renderRegulation(value) {
""" + render + """
renderRegulation({status:'blocked', control_enabled:true, raw_grid_w:2500,
  intended_candidate_w:200, offered_p1_w:2500, latched_at:'2026-10-11T07:54:59Z'});
assert.match(el('regulation-warning').textContent, /niet beschikbaar/);
assert.match(el('regulation-values').textContent, /Berekende correctie: 200 W/);
assert.match(el('regulation-values').textContent, /Gemeten aangeboden P1: 2500 W/);
assert.match(el('regulation-details').textContent, /Geblokkeerd sinds/);
renderRegulation({status:'ready', control_enabled:true, correction_guard:'recovering'});
assert.match(el('regulation-warning').textContent, /wordt hersteld/);
renderRegulation({status:'ready', control_enabled:true, correction_guard:'verified'});
assert.equal(el('regulation-warning').textContent, 'P1-correctie beschikbaar.');
renderRegulation(null);
assert.equal(el('regulation-panel').hidden, true);
"""
    result = subprocess.run([node], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_hems_ev_override_warning_clears_when_override_ends() -> None:
    node = shutil.which("node")
    assert node is not None
    warning = HEMS_HTML.split('      const evWarning = element("ev-storage-warning");')[1].split(
        '      const execution = pipeline.find')[0]
    script = """
const assert = require('node:assert/strict');
const evWarning = {};
let primitiveBoundary = {attributes:{execution_reason:'ev_storage_support_prohibited'}};
""" + warning + """
assert.equal(evWarning.hidden, false);
assert.match(evWarning.textContent, /standby/);
primitiveBoundary = {attributes:{execution_reason:'active canonical MEP segment boundary'}};
""" + warning + """
assert.equal(evWarning.hidden, true);
assert.equal(evWarning.textContent, '');
"""
    result = subprocess.run([node], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
