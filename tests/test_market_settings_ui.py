import json
import shutil
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def test_advanced_form_submits_fractional_maximum_wear_and_explicit_bonus_anchor():
    start = DASHBOARD_HTML.index("    const strategyControl =")
    end = DASHBOARD_HTML.index("    function renderEnergyDevices(", start)
    script = """
    const nodes = new Map();
    function element(id) {
      if (!nodes.has(id)) nodes.set(id, {value: '', checked: false, disabled: false,
        dataset: {}, contains: () => false, textContent: ''});
      return nodes.get(id);
    }
    const document = {activeElement: null};
    const formatTimestamp = value => value;
    let sent;
    async function fetch(url, options) {
      sent = {url, body: JSON.parse(options.body)};
      return {ok: true, json: async () => ({user_rules: sent.body})};
    }
    """ + DASHBOARD_HTML[start:end] + """
    (async () => {
      renderUserRules({revision: 3, strategy_trade_ceiling_percent: 37.5,
        market_wear_eur_per_kwh: 0.025, market_minimum_spread_eur_per_kwh: 0.05,
        solar_export_bonus: {enabled: true, latitude: 51.6, longitude: 4.6,
          annual_exported_kwh: 1300, annual_exported_at: '2026-11-15T09:00:00+00:00'}});
      element('rule-solar-confirm-annual').checked = true;
      await saveUserRules({preventDefault() {}});
      process.stdout.write(JSON.stringify(sent));
    })();
    """
    result = subprocess.run([shutil.which("node"), "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, check=True)
    sent = json.loads(result.stdout)
    assert sent["url"] == "api/user-rules"
    assert sent["body"]["strategy_trade_ceiling_percent"] == 37.5
    assert "maximum_trading_soc_percent" not in sent["body"]
    assert "strategy_position" not in sent["body"]
    assert sent["body"]["market_wear_eur_per_kwh"] == .025
    assert sent["body"]["solar_export_bonus"] == dict(
        enabled=True, latitude=51.6, longitude=4.6, annual_exported_kwh=1300,
        confirm_annual_export=True,
    )


def test_advanced_settings_are_a_separate_accessible_panel():
    assert 'aria-controls="settings-advanced"' in DASHBOARD_HTML
    assert 'id="settings-advanced" role="tabpanel"' in DASHBOARD_HTML
    assert 'data-settings-tab="advanced"' in DASHBOARD_HTML
    assert 'min="0" max="100" step="any"' in DASHBOARD_HTML
    assert "Bestaande vastgelegde opdrachten behouden" in DASHBOARD_HTML
