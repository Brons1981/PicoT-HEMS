"""User-facing dashboard acceptance: direct actions, evidence, and route differences."""
import json
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML, pipeline_result_nl


def js(name):
    start = DASHBOARD_HTML.index(f"    function {name}(")
    return DASHBOARD_HTML[start:DASHBOARD_HTML.index("\n    }", start)+6]


def run(names, expression):
    script = "\n".join(js(n) for n in names)
    return json.loads(subprocess.run(["node"], input=script +
        "\nconsole.log(JSON.stringify(" + expression + "));", text=True,
        encoding="utf-8", capture_output=True, check=True).stdout)


def test_reset_is_directly_above_navigation_and_no_technical_disclosures():
    markup = DASHBOARD_HTML.split("<script>")[0]
    assert markup.index('id="reset-planning"') < markup.index('class="dashboard-tabs"')
    assert "<details" not in markup
    for unwanted in ("planning-status", "pv-energy-timeline", "household-load-forecast",
                     "storage-energy-source-needs", "plan-explanation", "grid-charge-review"):
        assert f'id="{unwanted}"' not in markup


def test_planning_input_error_does_not_claim_complete():
    message = pipeline_result_nl(stage=1, state="failed", attributes={"error":"ED timeout"})
    assert "compleet" not in message
    assert "ED timeout" in message


def test_healthy_sources_are_silent_and_ed_is_not_assumed():
    faults = run(["dashboardFaults"], "dashboardFaults({pipeline:[{stage:1,health:'healthy',"
        "attributes:{sources:[{category:'pv',availability:'available',raw_state:0}]}}]})")
    assert faults == []
    faults = run(["dashboardFaults"], "dashboardFaults({pipeline:[{stage:1,health:'fault',"
        "state:'error',attributes:{error:'Prijsgegevens ontbreken'}}]})")
    assert "Prijsgegevens ontbreken" in str(faults)
    assert "Energy Devices" not in str(faults)


def test_ed_failure_and_source_failure_have_specific_messages():
    faults = run(["dashboardFaults"], "dashboardFaults({energy_device_catalog:{status:'error',"
        "error:'connection refused'},pipeline:[{stage:1,health:'fault',attributes:{sources:"
        "[{category:'nordpool',availability:'unavailable',entity_id:'sensor.price',"
        "error:'Geen tarieven'}]}}]})")
    assert "Energy Devices" in str(faults) and "connection refused" in str(faults)
    assert "Geen tarieven" in str(faults) and "sensor.price" in str(faults)


def test_same_charge_window_different_standby_is_visible_and_inputs_unchanged():
    value = run(["comparisonSegments", "comparisonDifferences"], """(() => {
      const a={segments:[{starts_at:'2026-10-24T22:00Z',ends_at:'2026-10-24T23:00Z',
        intent:'hold_storage'},{starts_at:'2026-10-24T23:00Z',ends_at:'2026-10-25T00:00Z',
        intent:'grid_charge'}]};
      const b={segments:[{...a.segments[0],intent:'self_consumption'},a.segments[1]]};
      const before=JSON.stringify([a,b]);
      return {diff:comparisonDifferences(comparisonSegments(a),comparisonSegments(b)),
        unchanged:before===JSON.stringify([a,b])}; })()""")
    assert value["unchanged"]
    assert len(value["diff"]) == 1
    assert value["diff"][0]["from"] == "hold_storage"
    assert value["diff"][0]["to"] == "self_consumption"


def test_old_offer_is_explicitly_partial_and_identical_routes_have_no_changes():
    value = run(["comparisonSegments", "comparisonDifferences"], """(() => {
      const a={main_signature:[['2026-10-24T22:00Z','2026-10-24T23:00Z','grid_charge']]};
      const x=comparisonSegments(a);return {x,diff:comparisonDifferences(x,x)};})()""")
    assert value["x"]["partial"] is True
    assert value["diff"] == []


DOM = """
class Element {
 constructor(tag) {this.tagName=tag.toUpperCase();this.children=[];this.textContent='';
  this.style={};this.dataset={};this.attrs={};this.classList={add(){}};}
 append(...children){this.children.push(...children);}
 appendChild(child){this.children.push(child);}
 replaceChildren(){this.children=[];}
 setAttribute(key,value){this.attrs[key]=value;}
 addEventListener(name,fn){this[name]=fn;}
}
const nodes={}; const element=id=>nodes[id]??=new Element('div');
const SVG_NAMESPACE='http://www.w3.org/2000/svg';
const document={createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag)};
const texts=node=>typeof node==='string'?node:
 [node.textContent,...node.children.map(texts)].join('|');
const walk=node=>typeof node==='string'?[]:[node,...node.children.flatMap(walk)];
let routeChoiceRequestPending=false;
const submitRouteChoice=()=>{throw Error('render must not submit');};
"""


def dom_run(names, script):
    source = DOM + "\n".join(js(n) for n in names) + script
    result = subprocess.run(["node"], input=source, encoding="utf-8", text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


COMPARISON = ["comparisonSegments", "comparisonDifferences", "comparisonMode",
              "appendPlanComparison", "planHistoryTime", "createSvgElement", "appendSvgText"]


def test_comparison_at_choice_has_shared_scale_real_modes_and_stale_actions_blocked():
    result=dom_run(COMPARISON+["renderRouteChoices"], """
const seg=(a,b,intent)=>({starts_at:a,ends_at:b,intent});
const start='2026-10-25T00:00Z',middle='2026-10-25T01:00Z',end='2026-10-25T02:00Z';
const automatic={timeline:{segments:[seg(start,middle,'standby'),
 seg(middle,end,'grid_requirement')]}};
const alternative={timeline:{segments:[seg(start,middle,'household_support_only'),
 seg(middle,end,'grid_requirement')]}};
const choice={status:'offered',plan_id:'a',current_plan_id:'a',revision:1,current_revision:1,
 token:'private',expires_at:'2999-01-01T00:00Z',offer:{automatic,alternative}};
const before=JSON.stringify(choice);
renderRouteChoices({choices:[choice]});
const card=element('route-choices');
const svg=walk(card).find(n=>n.tagName==='SVG');
const bars=walk(svg).filter(n=>n.tagName==='RECT'&&n.attrs.fill==='#df5c57');
const valid={text:texts(card),buttons:walk(card).filter(n=>n.type==='button').map(n=>n.textContent),
 widths:bars.map(n=>n.attrs.width),positions:bars.map(n=>n.attrs.x),
 unchanged:before===JSON.stringify(choice)};
renderRouteChoices({choices:[{...choice,current_plan_id:'new'}]});
console.log(JSON.stringify({valid,stale:texts(element('route-choices')),
 staleButtons:walk(element('route-choices')).filter(n=>n.type==='button').length}));
""")
    assert result["valid"]["unchanged"]
    assert result["valid"]["widths"] == ["480","480"]
    assert result["valid"]["positions"] == ["500","500"]
    assert result["valid"]["buttons"] == ["Kies PV-route", "Behoud automatisch plan"]
    assert "Stand-by → Slim ontladen" in result["valid"]["text"]
    assert "UTC+02:00" in result["valid"]["text"]
    assert "UTC+01:00" in result["valid"]["text"]
    assert "ouder plan" in result["stale"] and result["staleButtons"] == 0


def test_equal_export_rate_with_different_interval_boundaries_is_not_a_change():
    value=run(["comparisonSegments", "comparisonDifferences"], """(() => {
 const a={segments:[{starts_at:'2026-10-24T22:00Z',ends_at:'2026-10-24T23:00Z',
 intent:'storage_export',storage_export_target_wh:1000}]};
 const b={segments:[{...a.segments[0],ends_at:'2026-10-24T22:30Z',storage_export_target_wh:500},
 {...a.segments[0],starts_at:'2026-10-24T22:30Z',storage_export_target_wh:500}]};
 return comparisonDifferences(comparisonSegments(a),comparisonSegments(b));})()""")
    assert value == []


def test_manual_override_and_failed_source_remain_visible_together():
    result=dom_run(["dashboardFaults","renderDashboardFaults","renderStorageModeOverride"], """
renderDashboardFaults({pipeline:[{stage:1,health:'fault',
 attributes:{error:'Tarieven ontbreken'}}]});
renderStorageModeOverride({attributes:{manual_override_active:true}});
console.log(JSON.stringify({fault:texts(element('central-health')),
 visible:!element('central-health').hidden,override:!element('storage-mode-override').hidden,
 button:!element('reset-storage-mode-override').hidden}));
""")
    assert "Tarieven ontbreken" in result["fault"]
    assert result["visible"] and result["override"] and result["button"]


def test_connection_error_reappears_after_healthy_view():
    start=DASHBOARD_HTML.index("    async function loadView(")
    end=DASHBOARD_HTML.index("\n    }",start)+6
    source=DOM+js("dashboardFaults")+js("renderDashboardFaults")+DASHBOARD_HTML[start:end]
    source+="""
const captureDashboardState=()=>({});
const restoreDashboardState=()=>{};
const fetch=async()=>{throw Error('offline');};
(async()=>{renderDashboardFaults({pipeline:[]});await loadView();
console.log(JSON.stringify({visible:!element('central-health').hidden,
 text:texts(element('central-health'))}));})();
"""
    result=json.loads(subprocess.run(["node"],input=source,encoding="utf-8",text=True,
                                    capture_output=True,check=True).stdout)
    assert result["visible"] and "verbinding" in result["text"]



def test_new_fault_is_visible_even_while_full_render_is_deferred():
    result=dom_run(["dashboardFaults","renderDashboardFaults","renderStorageModeOverride",
                    "applyView"], """
let pendingView=null;
const shouldDeferRenderForSelection=()=>true;
const refreshLiveStatus=()=>{};
const renderView=()=>{throw Error('full render must defer');};
applyView({pipeline:[{stage:1,health:'fault',attributes:{error:'Actuele tarieven ontbreken'}},
 {stage:7,attributes:{manual_override_active:true}}]});
console.log(JSON.stringify({text:texts(element('central-health')),
 visible:!element('central-health').hidden,override:!element('storage-mode-override').hidden}));
""")
    assert result["visible"] and result["override"]
    assert "Actuele tarieven ontbreken" in result["text"]


def test_no_alternative_offer_does_not_announce_an_alternative_or_broken_comparison():
    result=dom_run(COMPARISON+["renderRouteChoices"], """
const automatic={main_signature:[['2026-10-24T22:00Z','2026-10-24T23:00Z','grid_requirement']]};
renderRouteChoices({choices:[{status:'offered',expires_at:'2999-01-01T00:00Z',
 offer:{automatic,alternative:null}}]});
console.log(JSON.stringify({text:texts(element('route-choices')),
 charts:walk(element('route-choices')).filter(n=>n.tagName==='SVG').length}));
""")
    assert "geen haalbaar PV-alternatief" in result["text"]
    assert "Tijdlijnvergelijking niet beschikbaar" not in result["text"]
    assert result["charts"] == 1



def test_hc_measurement_failure_is_named_without_blame_on_ed_service():
    faults = run(["dashboardFaults"], "dashboardFaults({pipeline:[{stage:1,health:'fault',"
        "attributes:{sources:[{category:'energy_devices',semantic_role:'controlled_load_measurement',"
        "availability:'unavailable',error:'Bronrapportage ouder dan 60 seconden'}]}}]})")
    assert "Home Climate-belastingsmeting" in str(faults)
    assert "ouder dan 60 seconden" in str(faults)
    assert "Energy Devices" not in str(faults)


def test_comparison_modes_use_the_same_palette_as_the_price_timeline():
    groups = {
        "canonical-charge": ("grid_requirement", "grid_charge", "charge", "charge_at_power"),
        "canonical-nom": ("nom", "balance_bidirectional", "balance_charge_only"),
        "canonical-support": ("self_consumption", "household_support_only",
                              "balance_discharge_only", "discharge_only"),
        "canonical-trade": ("storage_export", "discharge", "discharge_at_power"),
        "canonical-standby": ("standby", "stop_all", "hold_storage"),
    }
    expected = {"canonical-charge": "#df5c57", "canonical-nom": "#35a862",
                "canonical-support": "#3994e6", "canonical-trade": "#aab2bd",
                "canonical-standby": "#e3aa45"}
    for group, modes in groups.items():
        color = expected[group]
        assert f".price-swatch.{group} {{ background: {color}; }}" in DASHBOARD_HTML
        assert f".planner-window.{group} {{ fill: {color}; }}" in DASHBOARD_HTML
        assert f'["{group}", "{color}"]' in DASHBOARD_HTML
        colors = run(["comparisonMode"], json.dumps(modes) + ".map(m=>comparisonMode(m)[1])")
        assert colors == [color] * len(modes)


def test_execution_warning_uses_recorded_block_not_a_missing_confidence():
    result = dom_run(["dashboardFaults", "renderDashboardFaults"], """
renderDashboardFaults({plan_explanation:{readiness:{status:'blocked',
  warning_nl:'Uitvoering geblokkeerd: Zendure verbinding verbroken.'}}});
const failure=texts(element('central-health'));
renderDashboardFaults({plan_explanation:{readiness:{status:'already_active',
  confidence_percent:null,warning_nl:null,blockers:[]}}});
console.log(JSON.stringify({failure,hidden:element('central-health').hidden,
  text:texts(element('central-health'))}));
""")
    assert "Zendure verbinding verbroken" in result["failure"]
    assert result["hidden"] is True
    assert result["text"] == ""
