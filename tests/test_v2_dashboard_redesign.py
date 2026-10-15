"""Presentation contracts: measured SOC is never a forecast or missing-data fill."""

import json
import subprocess

import pytest

from picot.v2.web_ui import DASHBOARD_HTML


def _js_function(name: str, next_name: str, expression: str):
    start = DASHBOARD_HTML.index(f"    function {name}(")
    end = DASHBOARD_HTML.index(f"    function {next_name}(", start)
    result = subprocess.run(
        ["node"], input=DASHBOARD_HTML[start:end] +
        "\nconsole.log(JSON.stringify(" + expression + "));",
        text=True, encoding="utf-8", capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def test_soc_slots_keep_future_empty_and_use_only_observed_values():
    slots = _js_function("socQuarterSlots", "renderPriceTimeline", """
      socQuarterSlots(0, 172800000, {
        ends_at: new Date(1800000).toISOString(), points: [
          {at: new Date(0).toISOString(), soc_percent: 0},
          {at: new Date(900000).toISOString(), soc_percent: 42}
        ]}, 1800000)
    """)
    assert len(slots) == 192
    assert slots[0]["value"] == 42
    assert slots[1]["value"] == 42
    assert all(slot["value"] is None for slot in slots[2:])


def test_soc_gaps_invalid_values_zero_and_stale_end_are_distinct():
    slots = _js_function("socQuarterSlots", "renderPriceTimeline", """
      socQuarterSlots(0, 5400000, {
        ends_at: new Date(3600000).toISOString(), points: [
          {at: new Date(0).toISOString(), soc_percent: 0},
          {at: new Date(1800000).toISOString(), soc_percent: null},
          {at: new Date(2700000).toISOString(), soc_percent: 101},
          {at: new Date(3600000).toISOString(), soc_percent: 80}
        ]}, 5400000)
    """)
    assert [s["value"] for s in slots] == [0, None, None, 80, None, None]


def test_dashboard_primary_navigation_and_soc_subplot():
    nav = DASHBOARD_HTML.split('<nav class="dashboard-tabs"')[1].split('</nav>')[0]
    assert '>Vandaag</button>' in nav
    assert '>Historie</button>' in nav and '>Financieel</button>' in nav
    assert '>Dagplanning</button>' not in nav and '>Overzicht</button>' not in nav
    assert 'class: "soc-quarter-outline"' in DASHBOARD_HTML
    assert 'class: "soc-quarter-fill"' in DASHBOARD_HTML


def test_refresh_defers_native_input_and_keeps_unsaved_rules():
    assert 'document.activeElement?.matches("input, select, textarea")' in DASHBOARD_HTML
    assert 'form.dataset.dirty === "true"' in DASHBOARD_HTML
    assert 'document.addEventListener("focusout"' in DASHBOARD_HTML


@pytest.mark.parametrize("raw", [None, "", "unavailable", -1, 101])
def test_invalid_soc_never_becomes_zero(raw):
    slots = _js_function("socQuarterSlots", "renderPriceTimeline",
                         'socQuarterSlots(0, 900000, {ends_at: new Date(900000).toISOString(),'
                         'points: [{at: new Date(0).toISOString(), soc_percent: ' +
                         json.dumps(raw) + '}]}, 900000)')
    assert slots[0]["value"] is None


def test_current_quarter_is_clipped_to_now_without_filling_next_quarter():
    slots = _js_function("socQuarterSlots", "renderPriceTimeline", """
      socQuarterSlots(0, 2700000, {
        ends_at: new Date(1000000).toISOString(), points: [
          {at: new Date(0).toISOString(), soc_percent: 55}
        ]}, 1000000)
    """)
    assert [s["value"] for s in slots] == [55, 55, None]
    assert slots[1]["sampleAt"] == 1000000


def test_switch_history_uses_amsterdam_day_without_mutating_events():
    result = _js_function("switchHistoryEvents", "renderStorageModeTransitionHistory", """
      (() => {
        globalThis.financialDate = date => new Intl.DateTimeFormat('en-CA',
          {timeZone:'Europe/Amsterdam'}).format(date);
        const events = [{occurred_at:'2026-10-14T22:15:00Z'},
          {occurred_at:'2026-10-14T21:15:00Z'}, {occurred_at:'invalid'}];
        const before = JSON.stringify(events);
        return [switchHistoryEvents(events, 'today', '2026-10-15').length,
          switchHistoryEvents(events, 'all').length, before === JSON.stringify(events)];
      })()
    """)
    assert result == [1, 3, True]


def test_native_input_and_text_selection_defer_refresh_behavior():
    result = _js_function("shouldDeferRenderForSelection", "switchHistoryEvents", """
      (() => {
        globalThis.document = {activeElement:{matches: () => true}};
        globalThis.window = {getSelection: () => ({isCollapsed:true})};
        const input = shouldDeferRenderForSelection();
        document.activeElement.matches = () => false;
        const idle = shouldDeferRenderForSelection();
        window.getSelection = () => ({isCollapsed:false, toString: () => 'selected'});
        return [input, idle, shouldDeferRenderForSelection()];
      })()
    """)
    assert result == [True, False, True]


def test_dirty_form_is_preserved_after_focus_leaves_it():
    start = DASHBOARD_HTML.index("    function renderUserRules(")
    end = DASHBOARD_HTML.index("    async function saveUserRules(", start)
    script = """
      const form = {dataset:{dirty:'true'}, contains: () => false};
      const input = {value:'37', checked:true};
      const element = id => id === 'user-rules-form' ? form : input;
      const document = {activeElement:null};
    """ + DASHBOARD_HTML[start:end] + """
      renderUserRules({maximum_trading_soc_percent:25});
      console.log(JSON.stringify(input.value));
    """
    result = subprocess.run(["node"], input=script, text=True, encoding="utf-8",
                            capture_output=True, check=True)
    assert json.loads(result.stdout) == "37"


@pytest.mark.parametrize("outcome", ["success", "failure", "edited"])
def test_save_reply_only_acknowledges_submitted_draft(outcome):
    start = DASHBOARD_HTML.index("    function renderUserRules(")
    end = DASHBOARD_HTML.index("    function renderEnergyDevices(", start)
    harness = """
      const nodes = {};
      const element = id => nodes[id] ??= {
        value:'0', checked:false, dataset:{}, contains:()=>false
      };
      const document = {activeElement:null};
      let reply;
      const fetch = () => new Promise(resolve => {reply=resolve;});
      element('rule-trading-soc').value='37';
      element('user-rules-form').dataset.dirty='true';
      element('user-rules-form').dataset.editRevision='1';
    """
    script = harness + DASHBOARD_HTML[start:end] + """
      (async () => {
        const pending=saveUserRules({preventDefault(){}});
        const outcome=OUTCOME;
        if(outcome==='edited') {
          element('rule-trading-soc').value='41';
          element('user-rules-form').dataset.editRevision='2';
        }
        reply({ok:outcome!=='failure',status:500,json:async()=>({
          user_rules:{maximum_trading_soc_percent:37}
        })});
        await pending;
        renderUserRules({maximum_trading_soc_percent:25});
        console.log(JSON.stringify({value:element('rule-trading-soc').value,
          dirty:element('user-rules-form').dataset.dirty,
          disabled:element('save-user-rules').disabled,
          message:element('user-rules-status').textContent}));
      })();
    """.replace("OUTCOME", json.dumps(outcome))
    result = json.loads(subprocess.run(["node"], input=script, text=True,
                                      encoding="utf-8", capture_output=True, check=True).stdout)
    assert result["disabled"] is False
    if outcome == "edited":
        assert result["value"] == "41"
        assert result["dirty"] == "true"
        assert "niet opgeslagen" in result["message"]
    elif outcome == "failure":
        assert result["value"] == "37"
        assert result["dirty"] == "true"
    else:
        assert result["dirty"] == "false"


@pytest.mark.parametrize("replacement, count, active_elsewhere", [
    (True, 1, False), (False, 1, False), (True, 2, False), (True, 1, True),
])
def test_refresh_restores_matching_summary_focus_without_stealing_it(
    replacement, count, active_elsewhere,
):
    start = DASHBOARD_HTML.index("    function captureDashboardFocus(")
    end = DASHBOARD_HTML.index("    function captureDashboardState(", start)
    harness = """
      let candidates=[];
      const document={activeElement:null, querySelectorAll:()=>candidates};
      function summary(id) {
        return {tagName:'SUMMARY',id:'',isConnected:true,textContent:'Planning',
          parentElement:{closest:()=>({id})},getAttribute:()=>null,
          focus(){document.activeElement=this;}};
      }
      const original=summary('price-planner-details');
      document.activeElement=original;
      candidates=[original];
    """
    script = harness + DASHBOARD_HTML[start:end] + """
      const state=captureDashboardFocus();
      original.isConnected=false;
      const next=summary(REPLACEMENT ? 'price-planner-details' : 'other-details');
      const body={tagName:'BODY'};document.activeElement=body;candidates=[next];
      if (COUNT === 2) candidates.push(summary('price-planner-details'));
      if (ELSEWHERE) document.activeElement={tagName:'BUTTON'};
      restoreDashboardFocus(state);
      console.log(JSON.stringify(document.activeElement===next));
    """.replace("REPLACEMENT", json.dumps(replacement)).replace(
        "COUNT", str(count)
    ).replace("ELSEWHERE", json.dumps(active_elsewhere))
    result = subprocess.run(["node"], input=script, text=True, encoding="utf-8",
                            capture_output=True, check=True)
    assert json.loads(result.stdout) is (replacement and count == 1 and not active_elsewhere)
