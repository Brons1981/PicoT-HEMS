"""Live cards remain current while edits are preserved."""

import json
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def js(name):
    start = DASHBOARD_HTML.index(f"    function {name}(")
    return DASHBOARD_HTML[start : DASHBOARD_HTML.index("\n    }", start) + 6]


def run(script):
    return json.loads(
        subprocess.run(
            ["node"], input=script, text=True, encoding="utf-8", capture_output=True, check=True
        ).stdout
    )


def test_live_status_updates_during_selection():
    result = run(
        """
let pendingView=null, full=0, live=[];
const status={dataset:{}}; const element=()=>status;
const shouldDeferRenderForSelection=()=>true;
const renderView=()=>full++; const finishStartup=()=>{};
const refreshLiveStatus=view=>live.push(view.zendure_now.active_mode);
"""
        + js("applyView")
        + """
applyView({zendure_now:{active_mode:'Stand-by'}});
applyView({zendure_now:{active_mode:'Snel opladen'}});
console.log(JSON.stringify({full,live,pending:pendingView.zendure_now.active_mode}));
"""
    )
    assert result == {"full": 0, "live": ["Stand-by", "Snel opladen"], "pending": "Snel opladen"}


def test_observation_age_and_stale_state():
    result = run(
        js("modeFreshness")
        + """
const now=Date.parse('2026-10-24T18:00:00Z');
console.log(JSON.stringify([
modeFreshness({observed_at:'2026-10-24T17:59:30Z'},now),
modeFreshness({observed_at:'2026-10-24T17:57:00Z'},now),
modeFreshness({},now),modeFreshness({observed_at:'2026-10-24T18:01:00Z'},now)]));
"""
    )
    assert [v["stale"] for v in result] == [False, True, True, True]
    assert "30 s" in result[0]["label"]
    assert "Verouderd" in result[1]["label"]


def test_standby_is_distinct():
    assert (
        run(js("primitivePlanKind") + "console.log(JSON.stringify(primitivePlanKind('standby')));")
        == "canonical-standby"
    )
    for selector in (".price-swatch", ".planner-window-chip", ".price-bar", ".planner-window"):
        assert selector + ".canonical-standby" in DASHBOARD_HTML
    assert '["canonical-standby", "Stand-by — woning op netstroom"]' in DASHBOARD_HTML


def test_newer_independent_observation_is_not_rolled_back_by_planner_view():
    result = run(
        """
let latestStorageStatus={active_mode:'Stand-by',observed_at:'2026-10-24T18:01:00Z',
 origin:'unknown',set_at:null};
"""
        + js("currentStorageStatus")
        + """
console.log(JSON.stringify(currentStorageStatus({active_mode:'NOM',
 observed_at:'2026-10-24T18:00:00Z',origin:'picot',set_at:'old',planned_mode:'Snel opladen'})));
"""
    )
    assert result["active_mode"] == "Stand-by"
    assert result["origin"] == "unknown"
    assert result["set_at"] is None
    assert result["planned_mode"] == "Snel opladen"


def test_failed_independent_fetch_preserves_observation_and_releases_poll_lock():
    start = DASHBOARD_HTML.index("    async function loadStorageStatus(")
    end = DASHBOARD_HTML.index("\n    }", start) + 6
    result = run(
        """
let storageStatusLoading=false;
let latestStorageStatus={active_mode:'Stand-by',observed_at:'2026-10-24T18:01:00Z'};
let latestLiveView={}, calls=0, refreshed=0, release;
const fetch=()=>{calls++;return new Promise((_,reject)=>release=reject);};
const refreshLiveStatus=()=>refreshed++;
"""
        + DASHBOARD_HTML[start:end]
        + """
(async()=>{
 const pending=loadStorageStatus();
 await loadStorageStatus();
 release(new Error('network unavailable'));
 await pending;
 console.log(JSON.stringify({calls,refreshed,locked:storageStatusLoading,status:latestStorageStatus}));
})();
"""
    )
    assert result["calls"] == 1
    assert result["refreshed"] == 1
    assert result["locked"] is False
    assert result["status"]["observed_at"] == "2026-10-24T18:01:00Z"
