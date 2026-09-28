"""Large observer details must not erase an available canonical execution plan."""

import json
import shutil
import subprocess
from copy import deepcopy

import pytest
from test_market_revision_incident_history import large_market_run
from test_v2_mep_canonical_pipeline import _pipeline, _snapshot

from picot.v2.projection import project
from picot.v2.web_ui import DASHBOARD_HTML, MAX_WEB_VIEW_CHARACTERS, WebViewStore, build_web_view


@pytest.mark.parametrize("count", [1393, 4007])
def test_large_market_comparison_keeps_every_outcome_and_lossless_evidence(tmp_path, count):
    run = large_market_run(tmp_path, count)
    view = build_web_view(run, project(run))
    store = WebViewStore()
    store.publish(view)
    latest = json.loads(store.latest_json())
    assert "planning_status" in latest, "market detail must never erase the plan"
    assert len(store.latest_json()) <= MAX_WEB_VIEW_CHARACTERS
    assert latest["observer_only"] == view["observer_only"]
    assert latest["planning_status"]["execution"] == view["planning_status"]["execution"]
    comparison = latest["planning_status"]["market_revision_comparison"]
    card_summary = latest["pipeline"][3]["attributes"]["market_revision_comparison"]
    assert card_summary["details_reference"] == "planning_status.market_revision_comparison"
    assert card_summary["alternative_count"] == count
    assert "alternatives" not in card_summary
    assert comparison["winning_candidate_id"] == run.evaluation.winning_candidate_id
    assert comparison["incumbent_candidate_id"] == run.evaluation.incumbent_candidate_id
    assert len(comparison["alternatives"]) == count
    dictionary = comparison["evidence_dictionary"]
    for actual, expected in zip(
        comparison["alternatives"], run.outcomes.market_revision_evidence, strict=True,
    ):
        assert actual["candidate_id"] == expected.candidate_id
        assert actual["comparable_result_eur"] == expected.comparable_result_eur
        assert actual["delta_from_incumbent_eur"] == expected.delta_from_incumbent_eur
        assert actual["invalidity_reasons"] == list(expected.invalidity_reasons)
        item = dictionary[actual["evidence_ids_ref"]]
        if "ids" in item:
            ids = item["ids"]
        else:
            base = dictionary[item["base"]]["ids"]
            ids = base[:item["prefix_count"]] + item["middle"] + base[item["suffix_start"]:]
        assert ids == list(expected.evidence_ids)
    assert latest["planning_status"]["chosen_plan"] == view["planning_status"]["chosen_plan"]
    assert "dashboard_status" not in latest, "ordinary large comparisons need no detail loss"


@pytest.mark.parametrize("observer_only", [False, True])
def test_payload_pressure_preserves_current_plan_and_updates_then_recovers(
    tmp_path, observer_only,
):
    pipeline, _ = _pipeline(tmp_path)
    run = pipeline.run(planning_input=_snapshot(maximum_soc=1.0, current_soc=0.51))
    view = build_web_view(run, project(run))
    # The store must copy the actual execution authority, including live mode.
    view["observer_only"] = observer_only
    view["pipeline"][5]["attributes"]["observer_only"] = observer_only
    assert view["planning_status"]["chosen_plan"]["plan_id"]
    assert view["planning_status"]["execution_plans"][0]["segments"]
    original = deepcopy(view)
    store = WebViewStore()
    store.publish(view)
    review = {"available": True, "diagnostic_detail": "x" * MAX_WEB_VIEW_CHARACTERS}
    store.publish_grid_charge_review(review)
    latest = json.loads(store.latest_json())
    assert len(store.latest_json()) <= MAX_WEB_VIEW_CHARACTERS
    assert latest["run_id"] == view["run_id"]
    assert latest["observer_only"] is observer_only
    assert latest["pipeline"][5]["attributes"]["observer_only"] is observer_only
    for key in ("chosen_plan", "execution_plans", "decision", "execution", "attention"):
        assert latest["planning_status"][key] == view["planning_status"][key]
    assert latest["price_timeline"] == view["price_timeline"]
    assert latest["dashboard_status"]["status"] == "details_limited"
    assert "grid_charge_review" in latest["dashboard_status"]["omitted_sections"]
    assert view == original
    assert review["available"] is True

    # Subsequent worker updates must not perpetuate an empty/error-only view.
    financial = {"observer_only": True, "selection_permitted": False,
                 "commitment_permitted": False, "days": []}
    store.publish_financial_results(financial)
    after_update = json.loads(store.latest_json())
    assert after_update["planning_status"]["execution_plans"] == (
        view["planning_status"]["execution_plans"]
    )
    assert after_update["financial_results"] == financial
    store.publish_grid_charge_review({"available": False})
    store.publish(view)
    recovered = json.loads(store.latest_json())
    assert "dashboard_status" not in recovered
    for key, value in view["planning_status"].items():
        assert recovered["planning_status"][key] == value


def test_dashboard_explains_detail_limit_and_clears_notice_on_recovery():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify dashboard rendering"
    start = DASHBOARD_HTML.index("    function renderDashboardStatus(")
    end = DASHBOARD_HTML.index("    function ", start + 13)
    script = "const notice = {}; const element = () => notice;\n" + DASHBOARD_HTML[start:end]
    script += """
renderDashboardStatus({status: "details_limited", message_nl: "Extra detail beperkt"});
const limited = {...notice};
renderDashboardStatus(undefined);
process.stdout.write(JSON.stringify({limited, recovered: notice}));
"""
    result = subprocess.run([node], input=script, capture_output=True, text=True, check=True)
    rendered = json.loads(result.stdout)
    assert rendered["limited"] == {"hidden": False, "textContent": "Extra detail beperkt"}
    assert rendered["recovered"] == {"hidden": True, "textContent": ""}
