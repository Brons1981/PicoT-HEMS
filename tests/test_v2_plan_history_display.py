"""Historical comparison never replaces the executable plan or invents SOC."""

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


def test_repeated_amsterdam_hour_is_unambiguous():
    result = run(
        js("planHistoryTime")
        + """
console.log(JSON.stringify([
 planHistoryTime('2026-10-25T00:15:00Z'), planHistoryTime('2026-10-25T01:15:00Z')
]));
"""
    )
    assert "02:15" in result[0] and "02:15" in result[1]
    assert "UTC+02:00" in result[0] and "UTC+01:00" in result[1]


def test_history_defaults_to_previous_but_preserves_explicit_selection():
    result = run(
        js("planHistorySelection")
        + """
const plans=[{plan_id:'current',active:true},{plan_id:'previous'},{plan_id:'older'}];
console.log(JSON.stringify([
 planHistorySelection(plans,''),planHistorySelection(plans,'older'),
 planHistorySelection(plans,'current'),planHistorySelection(plans,'removed')
].map(v=>({current:v.current?.plan_id,selected:v.selected?.plan_id}))));
"""
    )
    assert result == [
        {"current": "current", "selected": "previous"},
        {"current": "current", "selected": "older"},
        {"current": "current", "selected": "current"},
        {"current": "current", "selected": "previous"},
    ]


def test_history_without_active_record_does_not_present_latest_as_current():
    result = run(
        js("planHistorySelection")
        + """
const result=planHistorySelection([{plan_id:'old'}],'');
console.log(JSON.stringify({current:result.current,selected:result.selected.plan_id}));
"""
    )
    assert result == {"current": None, "selected": "old"}


def test_historical_selection_renders_read_only_comparison_without_changing_plan_or_soc():
    functions = "\n".join(
        js(name)
        for name in (
            "planHistoryTime",
            "planHistorySelection",
            "planHistoryReason",
            "renderPlanHistory",
        )
    )
    result = run(
        """
class Element {
 constructor(tag) {this.tag=tag;this.children=[];this.textContent='';}
 append(...children) {this.children.push(...children);}
 replaceChildren() {this.children=[];}
}
const nodes={}; const element=id=>nodes[id]??=new Element('div');
const document={createElement:tag=>new Element(tag)};
const segments=[{starts_at:'2026-10-25T00:15:00Z',
 ends_at:'2026-10-25T01:15:00Z',primitive:'standby'}];
let planHistoryPlans=[{plan_id:'current',active:true,created_at:'2026-10-24T16:57:00Z',
 revision_reason:'projected_reserve_shortfall',segments},
 {plan_id:'previous',active:false,created_at:'2026-10-24T16:14:00Z',
 revision_reason:'current_soc_allows_grid_reduction',segments,soc_timeline:[999],segments_truncated:true}];
let planHistorySelectionId='previous',planHistoryOptionsKey='';
let planHistoryOmitted=0;
let planHistoryTruncated=true,planHistoryStale=true;
const currentView={plan_id:'current',soc:33};
const before=JSON.stringify([planHistoryPlans,currentView]);
"""
        + functions
        + """
renderPlanHistory();
function texts(node) {return typeof node==='string' ? [node] :
 [node.textContent??'',...node.children.flatMap(texts)];}
console.log(JSON.stringify({text:texts(element('plan-history-panels')).join('|'),
 unchanged:before===JSON.stringify([planHistoryPlans,currentView]),
 selected:element('plan-history-select').value,message:element('plan-history-message').textContent}));
"""
    )
    assert result["unchanged"] is True
    assert result["selected"] == "previous"
    assert "Huidig plan" in result["text"]
    assert "Historisch plan — niet actief" in result["text"]
    assert "Actuele SOC maakt minder netladen mogelijk" in result["text"]
    assert "Stand-by — woning op netstroom" in result["text"]
    assert "UTC+02:00" in result["text"] and "UTC+01:00" in result["text"]
    assert "999" not in result["text"]

    assert "meer segmenten" in result["text"]
    assert "meest recente plannen" in result["message"]
    assert "Niet ververst" in result["message"]
