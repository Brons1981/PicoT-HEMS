"""Exercise the financial renderer with real JavaScript and supplied view data."""

import json
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def _render(financial):
    start = DASHBOARD_HTML.index("    function renderFinancialResults(")
    end = DASHBOARD_HTML.index("    async function markPlannerStress(", start)
    harness = r"""
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.style={}; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children=[]; }
  setAttribute() {}
}
const root=new Element('root');
const document={createElement:tag=>new Element(tag)};
const element=()=>root;
const displayValue=v=>String(v);
const formatCurrency=v=>'€'+v;
const formatDutchNumber=v=>String(v);
const formatTimestamp=v=>String(v);
const financialValueClass=()=>'';
const renderHouseholdEnergySources=()=>new Element('sources');
function flatten(e) { return [e,...e.children.flatMap(flatten)]; }
"""
    script = harness + DASHBOARD_HTML[start:end] + (
        "renderFinancialResults(" + json.dumps(financial) + ");"
        "console.log(JSON.stringify(flatten(root).map(e=>({"
        "tag:e.tag,text:e.textContent??'',title:e.title??''}))));"
    )
    return json.loads(subprocess.run(
        ["node"], input=script, text=True, capture_output=True, check=True,
    ).stdout)


def test_incomplete_today_does_not_hide_older_days_or_cumulative_values():
    previous = {"day": "2026-09-23", "status": "available",
                "actual_energy_cost_eur": -0.5, "net_battery_value_eur": 0.2,
                "net_picot_value_eur": 0.1}
    today = {"day": "2026-09-26", "status": "incomplete",
             "reason": "measurement_coverage_incomplete"}
    nodes = _render({"today": today, "days": [previous, today], "cumulative": {
        "net_battery_value_eur": 0.2, "remaining_eur": 2407.2,
        "battery_purchase_eur": 2407.4, "repaid_fraction": 0.00008,
        "included_battery_days": 1, "excluded_battery_days": 1,
    }})
    texts = [n["text"] for n in nodes]
    assert "Resultaat per dag" in texts
    assert "2026-09-23" in texts
    assert "2026-09-26" in texts
    assert "€0.2" in texts
    assert any("netto terugverdiend" in text for text in texts)
    assert not any("NaN" in text or "undefined" in text for text in texts)


def test_partial_metrics_show_real_zero_and_negative_cost_with_exact_source_gap():
    today = {
        "day": "2026-09-26", "status": "available", "actual_energy_cost_eur": 99,
        "net_battery_value_eur": 99, "net_picot_value_eur": 99,
        "financial_metrics": {
            "status": "partial", "ends_at": "2026-09-26T20:07:51+00:00",
            "values": {
                "actual_energy_cost_eur": {"status": "available", "value_eur": -0.1},
                "grid_import_cost_eur": {"status": "available", "value_eur": 0},
                "grid_export_revenue_eur": {"status": "available", "value_eur": 0.1},
                "net_battery_value_eur": {"status": "incomplete", "value_eur": None,
                                          "reason": "measurement_coverage_incomplete",
                                          "missing_roles": ["pv_generation"]},
            },
            "measurement_coverage": {"pv_generation": {
                "source_entity_id": "sensor.pv", "gap_count": 1, "gaps": [{
                    "reason": "measurement_start_missing",
                    "starts_at": "2026-09-25T22:00:00+00:00",
                    "ends_at": "2026-09-26T05:34:40+00:00",
                }],
            }},
        },
    }
    nodes = _render({"today": today, "days": [today], "cumulative": {}})
    texts = [n["text"] for n in nodes]
    assert "€0" in texts
    assert "€0.1" in texts
    assert "—" in texts
    assert "Gedeeltelijk" in texts
    assert not any("99" in text or "NaN" in text or "undefined" in text for text in texts)
    assert any("PV-productie" in text and "sensor.pv" in text
               and "2026-09-26T05:34:40" in text for text in texts)


def test_empty_history_has_no_invented_payback():
    texts = [node["text"] for node in _render({})]
    assert "Nog geen batterijresultaten om op te tellen." in texts
    assert not any("€" in text or "NaN" in text for text in texts)
