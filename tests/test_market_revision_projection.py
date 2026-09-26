"""Canonical market comparison evidence reaches diagnostics and the dashboard."""

import json
import shutil
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from legacy_cp_pipeline import CanonicalPipeline

from picot.domain.market_revision_comparison import (
    MarketRevisionCandidateEvidence,
    MarketRevisionDayResult,
)
from picot.v2.projection import project
from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore, _build_planning_status


def comparison_run():
    run = CanonicalPipeline().run(captured_at=datetime(2026, 9, 26, 14, 29, 47, tzinfo=UTC))
    first = run.candidate_set.candidates[0]
    path = run.candidate_set.energy_paths[0]
    candidates = tuple(
        replace(first, candidate_id=name, energy_path_id=f"path:{name}")
        for name in ("retain", "remove", "shorten")
    )
    paths = tuple(replace(path, path_id=c.energy_path_id) for c in candidates)
    retained = MarketRevisionCandidateEvidence(
        candidate_id="retain", assignment_id="market:2026-09-26", variant="retained",
        horizon_start=run.planning_input.captured_at,
        horizon_end=datetime(2026, 9, 27, 22, tzinfo=UTC),
        days=(MarketRevisionDayResult("2026-09-26", 0.12, 0.9),
              MarketRevisionDayResult("2026-09-27", 0.55, 0.12)),
        grid_charge_wh=2400.0, terminal_storage_wh=4100.0,
        minimum_storage_wh=816.0, wear_cost_eur=0.0,
        comparable_result_eur=0.35, delta_from_incumbent_eur=0.0,
        invalidity_reasons=(), evidence_ids=("tariff:known", "forecast:known"),
    )
    evidence = (
        retained,
        replace(retained, candidate_id="remove", variant="removed",
                days=(MarketRevisionDayResult("2026-09-26", 0.08, 0.12),
                      MarketRevisionDayResult("2026-09-27", 0.25, 0.12)),
                grid_charge_wh=400.0, comparable_result_eur=-0.17,
                delta_from_incumbent_eur=-0.52),
        replace(retained, candidate_id="shorten", variant="shortened",
                terminal_storage_wh=2900.0, comparable_result_eur=None,
                delta_from_incumbent_eur=None,
                invalidity_reasons=("unequal_terminal_storage_without_recovery",)),
    )
    return replace(
        run,
        candidate_set=replace(run.candidate_set, candidates=candidates, energy_paths=paths),
        outcomes=replace(run.outcomes, candidate_ids=tuple(c.candidate_id for c in candidates),
                         outcomes=(), canonical_outcomes=(), market_revision_evidence=evidence),
        evaluation=replace(run.evaluation, winning_candidate_id="retain",
                           winning_energy_path_id="path:retain", incumbent_candidate_id="retain",
                           status="plan_retained", decisive_step="objective:financial_result",
                           reason="equivalent_or_worse_retains_incumbent"),
    )


def test_market_projection_preserves_all_candidate_values_and_canonical_choice():
    run = comparison_run()
    before = asdict(run)
    card = project(run).cards[3]
    comparison = _build_planning_status(run)["market_revision_comparison"]
    assert card.attributes["market_revision_comparison"] == comparison
    assert comparison["winning_candidate_id"] == "retain"
    assert comparison["incumbent_candidate_id"] == "retain"
    assert comparison["reason"] == run.evaluation.reason
    assert comparison["decisive_step"] == "objective:financial_result"
    alternatives = comparison["alternatives"]
    assert [a["candidate_id"] for a in alternatives] == ["retain", "remove", "shorten"]
    assert [a["selected"] for a in alternatives] == [True, False, False]
    assert alternatives[0]["horizon_start"] == "2026-09-26T14:29:47+00:00"
    assert alternatives[0]["horizon_end"] == "2026-09-27T22:00:00+00:00"
    assert alternatives[0]["days"] == [
        {"delivery_date": "2026-09-26", "import_cost_eur": 0.12, "export_revenue_eur": 0.9},
        {"delivery_date": "2026-09-27", "import_cost_eur": 0.55, "export_revenue_eur": 0.12},
    ]
    assert alternatives[1]["grid_charge_wh"] == 400.0
    assert alternatives[1]["terminal_storage_wh"] == 4100.0
    assert alternatives[1]["comparable_result_eur"] == -0.17
    assert alternatives[1]["delta_from_incumbent_eur"] == -0.52
    assert alternatives[2]["comparable_result_eur"] is None
    assert alternatives[2]["delta_from_incumbent_eur"] is None
    assert alternatives[2]["invalidity_reasons"] == [
        "unequal_terminal_storage_without_recovery",
    ]
    assert json.loads(json.dumps(comparison)) == comparison
    assert asdict(run) == before


def test_ordinary_run_has_no_market_comparison_and_old_outcomes_remain_compatible():
    run = CanonicalPipeline().run(captured_at=datetime(2026, 9, 26, tzinfo=UTC))
    assert run.outcomes.market_revision_evidence == ()
    assert project(run).cards[3].attributes["market_revision_comparison"] is None
    assert _build_planning_status(run)["market_revision_comparison"] is None


def test_market_evidence_cannot_reference_an_unrelated_or_duplicate_candidate():
    run = comparison_run()
    evidence = run.outcomes.market_revision_evidence[0]
    with pytest.raises(ValueError, match="unique outcome candidates"):
        replace(run.outcomes, market_revision_evidence=(replace(evidence, candidate_id="other"),))
    with pytest.raises(ValueError, match="unique outcome candidates"):
        replace(run.outcomes, market_revision_evidence=(evidence, evidence))


def test_projection_does_not_extend_missing_horizon_or_invent_financial_value():
    run = comparison_run()
    short = replace(run.outcomes.market_revision_evidence[0],
                    horizon_end=run.planning_input.captured_at + timedelta(hours=3),
                    comparable_result_eur=None, delta_from_incumbent_eur=None,
                    invalidity_reasons=("price_coverage_incomplete",))
    run = replace(run, outcomes=replace(run.outcomes, market_revision_evidence=(short,)))
    comparison = _build_planning_status(run)["market_revision_comparison"]
    row = comparison["alternatives"][0]
    assert row["horizon_end"] == short.horizon_end.isoformat()
    assert row["comparable_result_eur"] is None
    assert row["invalidity_reasons"] == ["price_coverage_incomplete"]


def test_dashboard_renders_losing_and_incomparable_market_alternatives():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the dashboard"
    functions = []
    for name in (
        "displayValue", "formatTimestamp", "formatCurrency", "formatDutchNumber",
        "formatMeasurement", "renderMarketRevisionComparison",
    ):
        start = DASHBOARD_HTML.index(f"    function {name}(")
        end = DASHBOARD_HTML.index("    function ", start + 13)
        functions.append(DASHBOARD_HTML[start:end])
    comparison = _build_planning_status(comparison_run())["market_revision_comparison"]
    script = "\n".join(functions) + "\n" + """
const document = {createElement(tag) {
  return {tag, children: [], dataset: {}, textContent: "", append(...nodes) {
    this.children.push(...nodes);
  }};
}};
const cards = [];
const addCard = (title, facts) => {
  const card = document.createElement("article");
  card.title = title;
  card.facts = facts;
  cards.push(card);
  return card;
};
""" + "\nrenderMarketRevisionComparison(" + json.dumps(comparison) + ", addCard);\n" + """
const collect = node => [node.textContent, ...node.children.flatMap(collect)];
process.stdout.write(JSON.stringify({cards, text: cards.flatMap(collect)}));
"""
    result = subprocess.run([node], input=script, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    text = rendered["text"]
    assert "Behouden (bestaand plan)" in text
    assert "Verwijderen" in text
    assert "Inkorten" in text
    assert "Onvoldoende vergelijkingsbewijs" in text
    assert "unequal_terminal_storage_without_recovery" in text
    assert any("2026-09-26: afname" in value and "2026-09-27: afname" in value for value in text)
    assert rendered["cards"][0]["facts"][1] == [
        "Weergave", "Vergelijking bij deze planbeslissing",
    ]
    assert rendered["cards"][0]["facts"][2:] == [
        ["Beslisregel", "objective:financial_result"],
        ["Reden", "equivalent_or_worse_retains_incumbent"],
    ]
    body = next(child for child in rendered["cards"][0]["children"] if child["tag"] == "table")
    rows = next(child for child in body["children"] if child["tag"] == "tbody")["children"]
    assert [row["dataset"]["candidateId"] for row in rows] == ["retain", "remove", "shorten"]
    assert [row["children"][1]["textContent"] for row in rows] == ["Ja", "Nee", "Nee"]


def market_view():
    comparison = _build_planning_status(comparison_run())["market_revision_comparison"]
    plans = [{"plan_id": "committed-plan", "energy_path_id": "committed-path"}]
    comparison = {**comparison, "execution_plans": plans}
    return {"planning_status": {
        "captured_at": comparison["comparison_captured_at"],
        "decision": {"status": "winner_selected"},
        "execution_plans": plans,
        "market_revision_comparison": comparison,
    }}


def test_last_comparison_stays_visible_for_exact_retained_plan_without_becoming_fresh():
    initial = market_view()
    store = WebViewStore()
    store.publish(initial)
    comparison = initial["planning_status"]["market_revision_comparison"]
    assert json.loads(store.latest_json())["planning_status"]["market_revision_comparison"] == (
        comparison
    )
    incoming = {"planning_status": {
        **initial["planning_status"], "captured_at": "2026-09-26T15:00:00+00:00",
        "decision": {"status": "plan_retained"}, "market_revision_comparison": None,
    }}
    for _ in range(2):
        store.publish(incoming)
        shown = json.loads(store.latest_json())["planning_status"]
        assert shown["market_revision_comparison"] == {**comparison, "retained": True}
        assert shown["captured_at"] == "2026-09-26T15:00:00+00:00"
    assert incoming["planning_status"]["market_revision_comparison"] is None
    # A fresh canonical comparison replaces the historical evidence immediately.
    store.publish(initial)
    assert json.loads(store.latest_json())["planning_status"]["market_revision_comparison"] == (
        comparison
    )
    # Restarting the web store cannot manufacture missing canonical evidence.
    restarted = WebViewStore()
    restarted.publish(incoming)
    restarted_status = json.loads(restarted.latest_json())["planning_status"]
    assert restarted_status["market_revision_comparison"] is None


@pytest.mark.parametrize(("status", "plan_id", "path_id"), [
    ("plan_retained", "changed-plan", "committed-path"),
    ("plan_retained", "committed-plan", "changed-path"),
    ("fallback_active", "committed-plan", "committed-path"),
    ("winner_selected", "committed-plan", "committed-path"),
    ("plan_retained", None, None),
])
def test_last_comparison_is_not_carried_to_changed_or_unavailable_plan(status, plan_id, path_id):
    store = WebViewStore()
    initial = market_view()
    store.publish(initial)
    store.publish({"planning_status": {
        **initial["planning_status"], "decision": {"status": status},
        "execution_plans": [{"plan_id": plan_id, "energy_path_id": path_id}] if plan_id else [],
        "market_revision_comparison": None,
    }})
    assert json.loads(store.latest_json())["planning_status"]["market_revision_comparison"] is None


def test_failed_comparison_cannot_become_a_retained_success_after_fallback():
    store = WebViewStore()
    initial = market_view()
    comparison = initial["planning_status"]["market_revision_comparison"]
    initial["planning_status"]["market_revision_comparison"] = {
        **comparison, "status": "fallback_active",
    }
    store.publish(initial)
    store.publish({"planning_status": {
        **initial["planning_status"], "decision": {"status": "plan_retained"},
        "market_revision_comparison": None,
    }})
    assert json.loads(store.latest_json())["planning_status"]["market_revision_comparison"] is None
