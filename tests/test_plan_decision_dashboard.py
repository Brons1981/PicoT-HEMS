"""Visible plan reasons must present actual, dated comparison evidence."""

import json
from copy import deepcopy

import pytest
from test_dashboard_attention import dom_run, js

from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore, _bounded_dashboard_view


def explanation(**changes):
    return {
        "status": "retained", "source": "comparison",
        "reason": "Het voordeel is te klein om het bestaande plan te wijzigen.",
        "assessed_at": "2026-10-31T14:04:00+00:00",
        "horizon_start": "2026-10-31T14:04:00+00:00",
        "horizon_end": "2026-11-01T23:00:00+00:00",
        "incumbent_cost_eur": 5.503, "alternative_cost_eur": 5.497,
        "improvement_eur": 0.006, "minimum_improvement_eur": 0.01,
        "initial_soc": 0.81, "solcast_basis": "central",
        "household_assumption": "Verwacht huisverbruik uit de beschikbare prognose",
        "ev_assumption": "Geen expliciet geplande autolading meegenomen",
        "execution_plans": [{"plan_id": "plan-a", "energy_path_id": "path-a"}],
        "evidence_retained": False, **changes,
    }


def render(value):
    return dom_run(["formatTimestamp", "formatDutchNumber", "renderPlanDecision"],
        "renderPlanDecision(" + json.dumps(value) + ");"
        "console.log(JSON.stringify({text:texts(element('plan-decision')),"
        "tags:walk(element('plan-decision')).map(n=>n.tagName)}));")


def test_explanation_is_directly_visible_in_planning_without_disclosures():
    markup = DASHBOARD_HTML.split("<script>")[0]
    assert 'id="plan-decision" class="timeline-panel" aria-live="polite"' in markup
    assert 'prepend(element("today-summary"), element("plan-decision"))' in js("initializeTabs")
    assert "renderPlanDecision(view.planning_status?.plan_decision)" in js("renderView")


def test_small_advantage_and_actual_assumptions_are_visible_without_rounding_to_zero():
    result = render(explanation())
    assert "Bestaand plan behouden" in result["text"]
    for value in ("0,006", "5,503", "5,497", "0,010", "81,00%", "central",
                  "Geen expliciet geplande autolading", "Laatste beoordeling", "Vergelijking",
                  "Verwacht huisverbruik uit de beschikbare prognose"):
        assert value in result["text"]
    assert "DETAILS" not in result["tags"]


def test_explanation_uses_text_nodes_and_never_executes_source_text():
    payload = '<img src=x onerror="throw Error(1)">'
    result = render(explanation(reason=payload, ev_assumption=payload))
    assert payload in result["text"]
    assert "IMG" not in result["tags"]
    assert "innerHTML" not in js("renderPlanDecision")


@pytest.mark.parametrize("missing", ["incumbent_cost_eur", "alternative_cost_eur",
                                    "improvement_eur", "horizon_end"])
def test_missing_evidence_never_becomes_a_zero_or_an_invented_saving(missing):
    result = render(explanation(**{missing: None}))
    assert "Geen vergelijkbare totale kosten vastgelegd" in result["text"]
    assert "Voordeel alternatief" not in result["text"]
    assert "5,503" not in result["text"]


def test_absent_explanation_and_failed_publication_are_honest():
    assert "Nog geen onderbouwde planuitleg beschikbaar" in render(None)["text"]
    result = render(explanation(status="publication_failed",
        reason="De vervanging kon niet worden opgeslagen; het eerdere plan blijft actief.",
        incumbent_cost_eur=None, alternative_cost_eur=None, improvement_eur=None))
    assert "Bestaand plan blijft actief" in result["text"]
    assert "Plan aangepast" not in result["text"]
    assert "Voordeel alternatief" not in result["text"]


def view(value=None):
    value = value or explanation()
    return {"planning_status": {
        "captured_at": "2026-10-31T14:04:00+00:00",
        "execution_plans": value["execution_plans"],
        "decision": {"status": "plan_retained"}, "plan_decision": value,
    }}


def test_normal_ticks_preserve_original_assessment_only_for_exact_plan_identity():
    original = view()
    store = WebViewStore()
    store.publish(original)
    incoming = view(explanation(source="observation", assessed_at="2026-10-31T14:15:00+00:00",
        incumbent_cost_eur=None, alternative_cost_eur=None, improvement_eur=None))
    before = deepcopy(incoming)
    for _ in range(2):
        store.publish(incoming)
        shown = json.loads(store.latest_json())["planning_status"]["plan_decision"]
        assert shown == {**original["planning_status"]["plan_decision"],
                         "evidence_retained": True}
    assert incoming == before
    assert "niet opnieuw berekend" in render(shown)["text"]
    fresh = view(explanation(improvement_eur=0.2))
    store.publish(fresh)
    assert json.loads(store.latest_json())["planning_status"]["plan_decision"] == (
        fresh["planning_status"]["plan_decision"]
    )
    restarted = WebViewStore()
    restarted.publish(incoming)
    assert json.loads(restarted.latest_json())["planning_status"]["plan_decision"] == (
        incoming["planning_status"]["plan_decision"]
    )


@pytest.mark.parametrize(("field", "replacement"), [
    ("execution_plans", [{"plan_id": "plan-b", "energy_path_id": "path-a"}]),
    ("execution_plans", [{"plan_id": "plan-a", "energy_path_id": "path-b"}]),
    ("execution_plans", []),
    ("decision", {"status": "fallback_active"}),
])
def test_stale_comparison_is_not_carried_to_new_or_failed_plan(field, replacement):
    store = WebViewStore()
    store.publish(view())
    fresh = view(explanation(source="observation", incumbent_cost_eur=None,
                            alternative_cost_eur=None, improvement_eur=None))
    fresh["planning_status"][field] = replacement
    store.publish(fresh)
    assert json.loads(store.latest_json())["planning_status"]["plan_decision"] == (
        fresh["planning_status"]["plan_decision"]
    )


def test_failed_publication_does_not_reuse_previous_success_and_bounded_view_keeps_reason():
    store = WebViewStore()
    store.publish(view())
    failed = view(explanation(source="observation", status="publication_failed"))
    store.publish(failed)
    assert json.loads(store.latest_json())["planning_status"]["plan_decision"] == (
        failed["planning_status"]["plan_decision"]
    )
    assert _bounded_dashboard_view(failed)["planning_status"]["plan_decision"] == (
        failed["planning_status"]["plan_decision"]
    )
