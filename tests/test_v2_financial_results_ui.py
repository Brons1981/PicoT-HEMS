"""Exercise the financial renderer with real JavaScript and supplied view data."""

import json
import subprocess

from picot.v2.web_ui import DASHBOARD_HTML


def _render(financial, interaction=""):
    start = DASHBOARD_HTML.index("    // Financial presentation only:")
    end = DASHBOARD_HTML.index("    async function markPlannerStress(", start)
    harness = r"""
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.style={}; this.attributes={}; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children=[]; }
  setAttribute(key,value) { this.attributes[key]=value; }
  querySelectorAll(tag) { return flatten(this).slice(1).filter(e=>e.tag===tag); }
  querySelector(tag) { return flatten(this).find(e=>e.tag===tag); }
  focus() { this.focused=true; }
  scrollIntoView() {}
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
        'const realFinancialDate = financialDate;'
        'financialDate = (now = new Date("2026-09-26T12:00:00Z")) => realFinancialDate(now);'
        'renderFinancialResults(' + json.dumps(financial) + ");"
        + interaction + "console.log(JSON.stringify(flatten(root).map(e=>({"
        "tag:e.tag,text:e.textContent??'',title:e.title??'',open:e.open??false,"
        "aria:e.attributes['aria-label']??'',focused:e.focused??false}))));"
    )
    return json.loads(subprocess.run(
        ["node"], input=script, text=True, encoding="utf-8", capture_output=True, check=True,
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
    assert "Je energieresultaat" in texts
    assert "23 sep 2026" in texts
    assert "26 sep 2026 · vandaag" in texts
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
    assert any("Onvolledig: onvoldoende gegevens" in text for text in texts)
    assert not any("99" in text or "NaN" in text or "undefined" in text for text in texts)
    assert any("PV-productie" in text and "sensor.pv" in text
               and "2026-09-26T05:34:40" in text for text in texts)


def test_empty_history_has_no_invented_payback():
    texts = [node["text"] for node in _render({})]
    assert "Nog geen batterijresultaten om op te tellen." in texts
    assert not any("€" in text or "NaN" in text for text in texts)


def test_complete_estimated_amounts_are_valid_with_derivation_in_evidence():
    today = {"day": "2026-09-26", "status": "incomplete", "financial_metrics": {
        "status": "estimated", "ends_at": "2026-09-26T21:00:00+00:00",
        "values": {
            "actual_energy_cost_eur": {"status": "available", "value_eur": 1.5},
            "net_battery_value_eur": {"status": "estimated", "value_eur": .25},
            "net_picot_value_eur": {"status": "estimated", "value_eur": -.1},
        },
        "inferences": [{"role": "pv_generation", "kind": "night_zero",
                        "starts_at": "2026-09-25T22:00:00+00:00",
                        "ends_at": "2026-09-26T05:30:00+00:00"}],
        "maximum_estimation_error_wh": .3,
    }}
    nodes = _render({"today": today, "days": [today], "cumulative": {
        "included_battery_days": 1, "excluded_battery_days": 0,
        "estimated_battery_days": 1,
    }})
    texts = [node["text"] for node in nodes]
    assert "≈ €0.25" in texts and "≈ €-0.1" in texts
    assert "€-1.5" in texts
    assert any("Geldig: volledig berekend met afgeleide meetgegevens" in text for text in texts)
    assert "Afgeleide meetgegevens" in texts
    assert any("1 met afgeleide bedragen" in t for t in texts)
    assert any("0.3 Wh" in t for t in texts)
    assert not any("Dagresultaat onvolledig" in t for t in texts)


def _presentation(expression):
    start = DASHBOARD_HTML.index("    // Financial presentation only:")
    end = DASHBOARD_HTML.index("    let financialSelectedWeek", start)
    script = DASHBOARD_HTML[start:end] + "\nconsole.log(JSON.stringify(" + expression + "));"
    return json.loads(subprocess.run(
        ["node"], input=script, text=True, encoding="utf-8", capture_output=True, check=True,
    ).stdout)


def test_week_dates_use_amsterdam_and_calendar_days_across_dst_and_year_boundary():
    assert _presentation('financialDate(new Date("2026-10-14T22:30:00Z"))') == "2026-10-15"
    assert _presentation('financialMonday("2027-01-01")') == "2026-12-28"
    assert _presentation('financialWeek([], "2026-10-19", "2026-10-25").map(r=>r.date)') == [
        "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
        "2026-10-23", "2026-10-24", "2026-10-25",
    ]


def test_metric_quality_is_independent_and_never_falls_back_to_old_value():
    day = {"status": "available", "net_battery_value_eur": 999, "financial_metrics": {
        "status": "estimated", "values": {
            "actual_energy_cost_eur": {"status": "available", "value_eur": -2},
            "net_picot_value_eur": {"status": "estimated", "value_eur": 0},
        },
    }}
    result = _presentation("financialColumns.map(([,name,sign])=>financialMetric(" +
                           json.dumps(day) + ",name,sign))")
    assert result == [
        {"value": 2, "quality": "available"},
        {"value": None, "quality": "incomplete"},
        {"value": 0, "quality": "estimated"},
    ]


def test_totals_preserve_negative_zero_missing_and_historical_quality_without_mutation():
    result = _presentation("""(()=>{
      const days=[{day:'2026-10-12',status:'available',net_battery_value_eur:-2},
        {day:'2026-10-14',financial_metrics:{values:{net_battery_value_eur:
          {status:'estimated',value_eur:0}}}}];
      const before=JSON.stringify(days);
      const total=financialWeekTotal(financialWeek(days,'2026-10-12','2026-10-14'),
        'net_battery_value_eur',1);
      return {total,unchanged:before===JSON.stringify(days)};
    })()""")
    assert result == {"total": {"value": -2, "count": 2, "expected": 3,
                                "qualities": ["historical", "incomplete", "estimated"]},
                      "unchanged": True}
    assert _presentation(
        "financialWeekTotal(financialWeek([],'2026-10-12','2026-10-14'),'x',1)"
    ) == {
        "value": None, "count": 0, "expected": 3, "qualities": ["incomplete"],
    }


def test_house_chart_uses_only_complete_reconciled_existing_source_allocation():
    day = {"financial_metrics": {"values": {
        "net_total_energy_value_eur": {"status": "estimated", "value_eur": 2}}},
        "household_energy_sources": {"household_load_kwh": 6, "sources": [
            {"source": "battery", "energy_kwh": 3},
            {"source": "pv_direct", "energy_kwh": 2},
            {"source": "grid", "energy_kwh": 1},
        ]}}
    assert _presentation("financialHouseSources(" + json.dumps(day) + ")") == {
        "values": [2, 1, 3], "total": 6, "quality": "estimated",
    }
    day["household_energy_sources"]["sources"][0]["energy_kwh"] = -1
    assert _presentation("financialHouseSources(" + json.dumps(day) + ")") is None
    day["household_energy_sources"]["sources"][0]["energy_kwh"] = 4
    assert _presentation("financialHouseSources(" + json.dumps(day) + ")") is None
    day["household_energy_sources"]["sources"][0]["energy_kwh"] = 3
    day["financial_metrics"]["values"]["net_total_energy_value_eur"]["status"] = "incomplete"
    assert _presentation("financialHouseSources(" + json.dumps(day) + ")") is None


def test_payback_estimate_uses_all_28_closed_calendar_days_and_excludes_today():
    expression = """(()=>{
      const days=Array.from({length:28},(_,i)=>({day:financialDateShift('2026-10-14',-i-1),
        status:'available',net_battery_value_eur:2,
        starts_at:financialDateShift('2026-10-14',-i-1)+'T00:00:00+02:00',
        ends_at:financialDateShift('2026-10-14',-i)+'T00:00:00+02:00'}));
      days.push({day:'2026-10-14',status:'available',net_battery_value_eur:999});
      return financialPaybackEstimate(days,{remaining_eur:200},'2026-10-14');
    })()"""
    assert _presentation(expression) == {
        "days": 100, "daily": 2, "estimated": False, "historical": True,
    }
    missing = _presentation(expression.replace("length:28", "length:27"))
    assert "1 van de laatste 28" in missing["reason"]
    negative = _presentation(expression.replace("value_eur:2", "value_eur:-2"))
    assert "niet positief" in negative["reason"]
    assert _presentation(
        "financialPaybackEstimate([],{remaining_eur:0,battery_purchase_eur:200},'2026-10-14')"
    ) == {
        "completed": True,
    }


def test_amount_marker_opens_the_day_evidence_with_keyboard_focus():
    day = {"day": "2026-09-26", "financial_metrics": {"values": {
        "net_battery_value_eur": {"status": "incomplete", "value_eur": None}}}}
    nodes = _render({"days": [day]}, """
      flatten(root).find(e=>e.tag==='button' &&
        e.attributes['aria-label']?.startsWith('Batterijvoordeel netto: 26 sep')).onclick();
    """)
    assert sum(node["open"] for node in nodes if node["tag"] == "details") == 2
    assert any(node["focused"] for node in nodes if node["tag"] == "summary")
    assert any("Batterijvoordeel netto: 26 sep" in node["aria"] for node in nodes)


def test_week_selection_opens_older_results_without_modifying_their_amounts():
    day = {"day": "2026-09-14", "status": "available", "actual_energy_cost_eur": -2.108}
    nodes = _render({"days": [day]}, """
      const select=flatten(root).find(e=>e.tag==='select');
      select.value='2026-09-14'; select.onchange();
    """)
    assert any(node["text"] == "€2.108" for node in nodes)
    assert any("Historisch" in node["aria"] for node in nodes)
    assert any(node["text"] == "14 sep 2026" for node in nodes)


def test_payback_rejects_partial_or_unproven_calendar_days_without_changing_amounts():
    expression = """(()=>{
      const days=Array.from({length:28},(_,i)=>{
        const day=financialDateShift('2026-10-14',-i-1);
        return {day,status:'available',net_battery_value_eur:2,
          starts_at:day+'T00:00:00+02:00',
          ends_at:financialDateShift(day,1)+'T00:00:00+02:00'};
      });
      CHANGE
      const before=JSON.stringify(days);
      const result=financialPaybackEstimate(days,{remaining_eur:200},'2026-10-14');
      return {result,unchanged:before===JSON.stringify(days),
        amount:financialMetric(days[0],'net_battery_value_eur').value};
    })()"""
    for change in [
        "days[0].ends_at=days[0].day+'T12:00:00+02:00';",
        "delete days[0].ends_at;",
        "days[0].starts_at='invalid';",
        "days[0].financial_metrics={values:{net_battery_value_eur:"
        "{status:'available',value_eur:2}}};",
        "days[0].starts_at=days[0].day+'T01:00:00+02:00';",
        "days[0].financial_metrics={values:{net_battery_value_eur:"
        "{status:'estimated',value_eur:2}},starts_at:days[0].starts_at,"
        "ends_at:days[0].day+'T12:00:00+02:00'};",
    ]:
        result = _presentation(expression.replace("CHANGE", change))
        assert "days" not in result["result"], change
        assert "volledige meetperiode" in result["result"]["reason"]
        assert result["unchanged"] and result["amount"] == 2


def test_full_calendar_day_accepts_dst_days_and_rejects_wrong_boundaries():
    cases = [
        ("2026-03-29", "2026-03-29T00:00:00+01:00", "2026-03-30T00:00:00+02:00", True),
        ("2026-10-25", "2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+01:00", True),
        ("2026-10-25", "2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+02:00", False),
        ("2026-10-13", "2026-10-12T22:00:00Z", "2026-10-13T22:00:00Z", True),
        ("2026-10-13", "2026-10-12T22:00:00Z", "2026-10-13T21:59:59.999Z", False),
    ]
    for day, start, end, expected in cases:
        record = {"day": day, "starts_at": start, "ends_at": end}
        assert _presentation("financialFullDay(" + json.dumps(record) + ")") is expected


def test_deep_disclosures_keep_open_and_closed_states_across_refresh():
    financial = {"days": [{"day": "2026-09-26", "financial_metrics": {
        "status": "estimated", "values": {},
        "inferences": [{"role": "pv_generation", "kind": "night_zero"}],
        "measurement_coverage": {"pv_generation": {"gaps": [{
            "reason": "measurement_start_missing"}]}},
    }}]}
    interaction = """
      const titles=['Onderbouwing van de tijdschatting','Afgeleide meetgegevens',
        'Ontbrekende meetgegevens'];
      const find=title=>flatten(root).find(e=>e.tag==='details' &&
        e.children[0]?.textContent===title);
      titles.forEach(title=>find(title).open=true);
      renderFinancialResults(DATA);
      if(!titles.every(title=>find(title).open)) throw Error('Opened disclosure lost on refresh');
      titles.forEach(title=>find(title).open=false);
      renderFinancialResults(DATA);
      if(titles.some(title=>find(title).open)) throw Error('Closed disclosure reopened');
    """.replace("DATA", json.dumps(financial))
    _render(financial, interaction)



def test_stored_value_column_has_one_header_explanation_and_no_disclosure():
    base = {"day": "2026-09-26", "status": "available", "net_battery_value_eur": .2}
    without = _render({"days": [base]})
    for value in [0, -0.3, 2.104]:
        record = {**base, "estimated_battery_value": {
            "status": "estimated", "value_eur": value}}
        nodes = _render({"days": [record]})
        assert any(n["tag"] == "td" and n["text"] == f"≈ €{value}" for n in nodes)
        header = next(n for n in nodes if n["text"] == "Geschatte batterijwaarde ")
        assert "24 uur" in header["title"]
        assert sum(n["tag"] == "details" for n in nodes) == sum(
            n["tag"] == "details" for n in without)
    assert any(n["tag"] == "td" and n["text"] == "—" for n in without)



def test_stored_value_help_can_be_opened_and_closed_without_row_disclosures():
    _render({"days": []}, """
      const button=flatten(root).find(e=>e.tag==='button' &&
        e.attributes['aria-controls']==='financial-stored-value-help');
      const help=flatten(root).find(e=>e.id==='financial-stored-value-help');
      if(!button || !help || !help.hidden) throw Error('Missing collapsed help');
      button.onclick();
      if(help.hidden || button.attributes['aria-expanded']!=='true') throw Error('Cannot open');
      button.onclick();
      if(!help.hidden || button.attributes['aria-expanded']!=='false') throw Error('Cannot close');
    """)


def test_complete_derived_week_has_no_warning_markers_for_amounts_totals_or_sources():
    days = [{"day": f"2026-09-{day}", "financial_metrics": {
        "status": "estimated", "values": {name: {"status": "estimated", "value_eur": .25}
            for name in ["actual_energy_cost_eur", "net_battery_value_eur",
                         "net_picot_value_eur", "net_total_energy_value_eur"]}},
        "household_energy_sources": {"household_load_kwh": 6, "sources": [
            {"source": "battery", "energy_kwh": 3}, {"source": "pv_direct", "energy_kwh": 2},
            {"source": "grid", "energy_kwh": 1}]}} for day in range(21, 27)]
    nodes = _render({"days": days})
    assert not any(n["tag"] == "button" and n["text"] == "!" for n in nodes)
    assert not any(n["text"].startswith("~ ") for n in nodes)
    assert any("0 dagen met bijzonderheden" in n["text"] for n in nodes)
    assert any("afgeleide meetgegevens" in n["text"] for n in nodes)


def test_missing_metric_keeps_warning_next_to_valid_derived_metric():
    day = {"day": "2026-09-26", "financial_metrics": {"status": "partial", "values": {
        "actual_energy_cost_eur": {"status": "estimated", "value_eur": 1},
        "net_battery_value_eur": {"status": "incomplete", "value_eur": None},
        "net_picot_value_eur": {"status": "estimated", "value_eur": 0}}}}
    nodes = _render({"days": [day]})
    warnings = [n for n in nodes if n["tag"] == "button" and "26 sep" in n["aria"]]
    assert len(warnings) == 1
    assert warnings[0]["text"] == "!"
    assert "Batterijvoordeel netto" in warnings[0]["aria"]


def test_pending_current_quarter_is_neutral_and_keeps_completed_period_visible():
    days = [{"day": f"2026-09-{day}", "financial_metrics": {
        "status": "estimated", "ends_at": "2026-09-26T12:00:00Z",
        "values": {name: {"status": "estimated", "value_eur": .25}
            for name in ["actual_energy_cost_eur", "net_battery_value_eur",
                         "net_picot_value_eur", "net_total_energy_value_eur"]}}}
        for day in range(21, 27)]
    days[-1]["financial_metrics"]["pending_period"] = {
        "starts_at": "2026-09-26T12:00:00Z", "ends_at": "2026-09-26T12:07:00Z",
        "reason": "current_quarter_not_closed"}
    nodes = _render({"days": days})
    assert any("Vandaag tot 2026-09-26T12:00:00Z" in n["text"] for n in nodes)
    assert any("Het lopende kwartier is nog niet afgerond" in n["text"] for n in nodes)
    assert not any(n["tag"] == "button" and n["text"] == "!" for n in nodes)
    assert not any("Dagresultaat onvolledig" in n["text"] for n in nodes)
