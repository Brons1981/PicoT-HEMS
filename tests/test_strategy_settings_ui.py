"""Exercise the actual dashboard script with delayed and failed API responses."""

import json
import shutil
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def run_strategy_script(body):
    start = DASHBOARD_HTML.index("    const strategyControl =")
    end = DASHBOARD_HTML.index("    function renderEnergyDevices(", start)
    harness = """
      const nodes = new Map();
      function element(id) {
        if (!nodes.has(id)) nodes.set(id, {value:'', checked:false, disabled:false,
          dataset:{}, contains:()=>false, textContent:''});
        return nodes.get(id);
      }
      const document = {activeElement:null};
      const formatTimestamp = value => value;
      const calls = [];
      const replies = [];
      async function fetch(url, options) {
        calls.push({url, body:JSON.parse(options.body)});
        return new Promise(resolve => replies.push(resolve));
      }
      function rules(position, revision, effective) {
        return {strategy_position:position, revision,
          strategy_trade_ceiling_percent:37.5, market_wear_eur_per_kwh:.05,
          maximum_trading_soc_percent:effective, strategy_mapping:{
            position,
            label:['Zelfverbruik','Meer zelfverbruik','Gebalanceerd','Meer handel'][position],
            trade_ceiling_percent:37.5, capacity_factor:position/3,
            effective_trading_soc_percent:effective}};
      }
      const tick = () => new Promise(resolve => setImmediate(resolve));
      function reply(value) { replies.shift()({ok:true,json:async()=>({user_rules:value})}); }
    """
    script = harness + DASHBOARD_HTML[start:end] + "\n(async()=>{\n" + body + "\n})();"
    result = subprocess.run([shutil.which("node"), "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


def test_slider_has_four_discrete_available_stops_and_visible_disabled_trade():
    assert 'id="rule-strategy-position" type="range" min="0" max="3" step="1"' in DASHBOARD_HTML
    assert 'id="strategy-trade-only" disabled' in DASHBOARD_HTML
    assert 'aria-describedby="strategy-trade-only-reason"' in DASHBOARD_HTML
    assert 'addEventListener("change", changeStrategyPosition)' in DASHBOARD_HTML


def test_slider_posts_only_position_preserves_draft_and_displays_producer_mapping():
    result = run_strategy_script("""
      renderUserRules(rules(2, 5, 25));
      element('user-rules-form').dataset.dirty='true';
      element('rule-trading-soc').value='50';
      element('rule-market-wear').value='.123';
      element('rule-strategy-position').value='0';
      const pending=changeStrategyPosition();
      await tick();
      reply(rules(0, 6, 0));
      await pending;
      console.log(JSON.stringify({calls, draft:element('rule-trading-soc').value,
        wear:element('rule-market-wear').value, dirty:element('user-rules-form').dataset.dirty,
        position:element('rule-strategy-position').value,
        evidence:element('strategy-parameters').textContent}));
    """)
    assert result["calls"] == [{"url": "api/user-rules", "body": {"strategy_position": 0}}]
    assert result["draft"] == "50"
    assert result["wear"] == ".123"
    assert result["dirty"] == "true"
    assert result["position"] == 0
    assert "Handelsmaximum: 0%" in result["evidence"]
    assert "bovengrens: 37.5%" in result["evidence"]


def test_rapid_changes_are_serialized_and_last_choice_survives_stale_poll():
    result = run_strategy_script("""
      renderUserRules(rules(2, 5, 25));
      element('rule-strategy-position').value='0';
      const pending=changeStrategyPosition();
      await tick();
      element('rule-strategy-position').value='1';
      changeStrategyPosition();
      element('rule-strategy-position').value='3';
      changeStrategyPosition();
      renderUserRules(rules(2, 5, 25));
      const during=element('rule-strategy-position').value;
      const beforeReply=calls.length;
      reply(rules(0, 6, 0));
      await tick();
      reply(rules(3, 7, 37.5));
      await pending;
      renderUserRules(rules(0, 6, 0));
      console.log(JSON.stringify({calls,during,beforeReply,
        position:element('rule-strategy-position').value,
        evidence:element('strategy-parameters').textContent}));
    """)
    assert result["beforeReply"] == 1
    assert result["during"] == "3"
    assert [call["body"] for call in result["calls"]] == [
        {"strategy_position": 0}, {"strategy_position": 3},
    ]
    assert result["position"] == 3
    assert "Revisie 7" in result["evidence"]


def test_failed_change_restores_last_confirmed_position_and_reports_uncertainty():
    result = run_strategy_script("""
      renderUserRules(rules(2, 5, 25));
      element('rule-strategy-position').value='0';
      const pending=changeStrategyPosition();
      await tick();
      replies.shift()({ok:false,status:503});
      await pending;
      console.log(JSON.stringify({position:element('rule-strategy-position').value,
        text:element('strategy-status').textContent, running:strategyControl.running}));
    """)
    assert result["position"] == 2
    assert "niet bevestigd" in result["text"]
    assert result["running"] is None


def test_unavailable_fifth_position_cannot_be_submitted():
    result = run_strategy_script("""
      renderUserRules(rules(2, 5, 25));
      element('rule-strategy-position').value='4';
      await changeStrategyPosition();
      console.log(JSON.stringify(calls));
    """)
    assert result == []


def test_slider_event_does_not_mark_unrelated_settings_as_edited():
    start = DASHBOARD_HTML.index("    function markUserRulesEdited(")
    end = DASHBOARD_HTML.index('    element("user-rules-form").addEventListener', start)
    script = """
      const form = {dataset:{dirty:'false', editRevision:'8'}};
      const element = () => form;
    """ + DASHBOARD_HTML[start:end] + """
      markUserRulesEdited({target:{id:'rule-strategy-position'}});
      const slider={...form.dataset};
      markUserRulesEdited({target:{id:'rule-market-wear'}});
      console.log(JSON.stringify({slider,advanced:form.dataset}));
    """
    result = json.loads(subprocess.run([shutil.which("node"), "-"], input=script, text=True,
                                      encoding="utf-8", capture_output=True, check=True).stdout)
    assert result["slider"] == {"dirty": "false", "editRevision": "8"}
    assert result["advanced"] == {"dirty": "true", "editRevision": "9"}
