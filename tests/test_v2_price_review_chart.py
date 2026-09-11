"""Exercise the actual SVG renderer without requiring a browser in CI."""

import json
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def test_price_renderer_clips_hatching_and_draws_actual_soc_with_gaps():
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
const forecast=[{at:at(0),soc_percent:20},{at:at(60),soc_percent:80}];
const actual={points:[{at:at(0),soc_percent:20},{at:at(15),soc_percent:null},
  {at:at(30),soc_percent:30}],ends_at:at(45)};
const before=JSON.stringify([forecast,actual]);
renderPriceTimeline({display_starts_at:at(0),display_ends_at:at(60),
  points:[-.1,0,.2,.4].map((value,i)=>({starts_at:at(i*15),ends_at:at((i+1)*15),
    value_eur_per_kwh:value})),market_timezone:'Europe/Amsterdam'},at(45),
  [{starts_at:at(7.5),ends_at:at(22.5),kind:'canonical-charge',label:'Netladen'}],
  forecast,actual);
function flatten(e) {
  return typeof e==='object' ? [e,...e.children.flatMap(flatten)] : [];
}
console.log(JSON.stringify({nodes:flatten(root).map(e=>({tag:e.tag,...e.attrs})),
  unchanged:before===JSON.stringify([forecast,actual])}));
"""
    process = subprocess.run(
        ["node"], input=harness + renderer + exercise, text=True, capture_output=True, check=True
    )
    result = json.loads(process.stdout)
    nodes = result["nodes"]
    hatches = [n for n in nodes if n.get("class", "").startswith("optimized-price-part")]
    assert len(hatches) == 2
    assert [n["width"] for n in hatches] == [141.75, 141.75]
    assert all(n["fill"] == "url(#price-hatch-canonical-charge)" for n in hatches)
    assert all(n["height"] > 0 for n in hatches)  # Negative and zero prices still hatch.
    actual = [n for n in nodes if n.get("class") == "soc-line soc-actual"]
    assert len(actual) == 2  # No line across the 15-minute unavailable interval.
    assert actual[0]["d"].endswith("H 365.5")
    assert "H 932.5" in actual[1]["d"]  # Stops at observed 00:45, not forecast end 01:00.
    assert len([n for n in nodes if n.get("class") == "soc-line canonical-charge"]) == 1
    assert result["unchanged"] is True
