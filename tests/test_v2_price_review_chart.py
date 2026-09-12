"""Exercise the actual SVG renderer without requiring a browser in CI."""

import json
import subprocess

import pytest

from picot.v2.web_ui import DASHBOARD_HTML


@pytest.mark.parametrize("optimized", [True, False])
def test_price_renderer_clips_hatching_and_draws_actual_soc_with_gaps(optimized):
    start = DASHBOARD_HTML.index("    function renderPriceTimeline(")
    end = DASHBOARD_HTML.index("    function displayValue(", start)
    renderer = DASHBOARD_HTML[start:end]
    harness = r"""
class Element {
  constructor(tag, attrs={}) { this.tag=tag; this.attrs=attrs; this.children=[]; }
  appendChild(child) { this.children.push(child); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children=[]; }
  addEventListener() {}
}
const root=new Element('root');
const document={createElement:tag=>new Element(tag)};
const element=()=>root;
const createSvgElement=(tag,attrs)=>new Element(tag,attrs);
const appendSvgText=(parent,text,attrs,kind)=>parent.appendChild(
  new Element('text',{...attrs,text,class:kind}));
const formatTimestamp=v=>v;
const formatChartTime=v=>new Date(v).toISOString().slice(11,16);
const formatPrice=v=>String(v);
const formatConfidence=v=>String(v);
const primitivePlanKind=()=> 'canonical-charge';
Date.now=()=>Date.parse('2026-09-11T00:45:00Z');
"""
    exercise = r"""
const at=m=>new Date(Date.parse('2026-09-11T00:00:00Z')+m*60000).toISOString();
const forecast=[{at:at(0),soc_percent:20},{at:at(30),soc_percent:50},
  {at:at(30),soc_percent:10,break_before:true},{at:at(60),soc_percent:80}];
const actual={points:[{at:at(0),soc_percent:20},{at:at(15),soc_percent:null},
  {at:at(30),soc_percent:30}],ends_at:at(45)};
const before=JSON.stringify([forecast,actual]);
renderPriceTimeline({display_starts_at:at(0),display_ends_at:at(60),
  points:[-.1,0,.2,.4].map((value,i)=>({starts_at:at(i*15),ends_at:at((i+1)*15),
    value_eur_per_kwh:value})),market_timezone:'Europe/Amsterdam'},at(45),
  [{starts_at:at(7.5),ends_at:at(22.5),kind:'canonical-charge',label:'Netladen',optimized:true}],
  forecast,actual);
function flatten(e) {
  return typeof e==='object' ? [e,...e.children.flatMap(flatten)] : [];
}
console.log(JSON.stringify({nodes:flatten(root).map(e=>({tag:e.tag,...e.attrs})),
  unchanged:before===JSON.stringify([forecast,actual])}));
"""
    exercise = exercise.replace("optimized:true", "optimized:" + str(optimized).lower())
    process = subprocess.run(
        ["node"], input=harness + renderer + exercise, text=True, capture_output=True, check=True
    )
    result = json.loads(process.stdout)
    nodes = result["nodes"]
    hatches = [n for n in nodes if n.get("class", "").startswith("optimized-price-part")]
    assert len(hatches) == (2 if optimized else 0)
    assert [n["width"] for n in hatches] == ([141.75, 141.75] if optimized else [])
    assert all(n["fill"] == "url(#price-hatch-canonical-charge)" for n in hatches)
    assert all(n["height"] > 0 for n in hatches)  # Negative and zero prices still hatch.
    actual = [n for n in nodes if n.get("class") == "soc-line soc-actual"]
    assert len(actual) == 2  # No line across the 15-minute unavailable interval.
    assert actual[0]["d"].endswith("H 365.5")
    assert "H 932.5" in actual[1]["d"]  # Stops at observed 00:45, not forecast end 01:00.
    assert len([n for n in nodes if n.get("class") == "soc-line canonical-charge"]) == 2
    assert result["unchanged"] is True


def test_hatching_compares_behavior_to_original_not_plan_revision():
    start = DASHBOARD_HTML.index("    function pricePlanParts(")
    end = DASHBOARD_HTML.index("    function movePanelContent(", start)
    script = DASHBOARD_HTML[start:end]
    exercise = r"""
const at=m=>new Date(Date.parse('2026-09-11T00:00:00Z')+m*60000).toISOString();
const seg=(a,b,primitive='charge_at_power',power=2400)=>({starts_at:at(a),ends_at:at(b),
  primitive,requested_power_w:power,charge_source_policy:'grid_allowed'});
const original={plans:[{plan_id:'initial',execution_scope_id:'battery',segments:[
  seg(0,15,'balance_bidirectional',null),seg(15,45),seg(45,60,'balance_discharge_only',null)
]}]};
const plan={plan_id:'revision-99',execution_scope_id:'battery'};
const before=JSON.stringify(original);
console.log(JSON.stringify({
  unchanged:pricePlanParts(seg(15,45),plan,original),
  extension:pricePlanParts(seg(7.5,45),plan,original),
  removed:pricePlanParts(seg(15,60,'balance_discharge_only',null),plan,original),
  power:pricePlanParts(seg(15,45,'charge_at_power',1200),plan,original),
  missing:pricePlanParts(seg(15,45),plan,{}),
  otherScope:pricePlanParts(seg(15,45),{execution_scope_id:'other'},original),
  outside:pricePlanParts(seg(60,75),plan,original),
  immutable:before===JSON.stringify(original)
}));
"""
    result = json.loads(subprocess.run(
        ["node"], input=script + exercise, text=True, capture_output=True, check=True
    ).stdout)
    assert [p["optimized"] for p in result["unchanged"]] == [False]
    assert [p["optimized"] for p in result["extension"]] == [True, False]
    assert result["extension"][0]["ends_at"].endswith("00:15:00.000Z")
    assert [p["optimized"] for p in result["removed"]] == [True, False]
    assert result["power"][0]["optimized"] is True
    for key in ("missing", "otherScope", "outside"):
        assert result[key][0]["optimized"] is False
    assert result["immutable"] is True


@pytest.mark.parametrize("days,expected", [
    ([], "Kostenverschil nog niet beschikbaar"),
    ([{"day": "2026-09-11", "status": "incomplete", "reason": "price_coverage_incomplete"}],
     "Kostenverschil nog niet beschikbaar: Niet alle prijzen beschikbaar"),
    ([{"day": "2026-09-11", "status": "available", "finalized": False,
       "cost_difference_eur": -0.12}], "Kostenverschil bij minder netladen (2026-09-11): €-0.12"),
])
def test_cost_difference_is_visible_above_table_or_explains_missing_data(days, expected):
    start = DASHBOARD_HTML.index("    function renderGridChargeReview(")
    end = DASHBOARD_HTML.index("    function renderFinancialResults(", start)
    harness = r"""
class Element {
  constructor() { this.children=[]; this.style={}; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children=[]; }
}
const root=new Element();
const document={createElement:()=>new Element()};
const element=()=>root;
const formatCurrency=v=>'€'+v;
const formatDutchNumber=v=>String(v);
function texts(e) { return [e.textContent??'',...e.children.flatMap(texts)]; }
"""
    script = harness + DASHBOARD_HTML[start:end] + (
        "renderGridChargeReview(" + json.dumps({"days": days}) + ");"
        "console.log(JSON.stringify(texts(root)));"
    )
    texts = json.loads(subprocess.run(
        ["node"], input=script, text=True, capture_output=True, check=True
    ).stdout)
    assert any(expected in text for text in texts)
