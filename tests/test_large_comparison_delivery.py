"""Large comparisons remain inspectable without displacing the active plan."""
import json
from dataclasses import asdict
from datetime import timedelta

from test_market_revision_incident_history import large_market_run

from picot.v2.planning_incident_history import (
    PlanningIncidentHistory,
    _basic_incident_record,
    _record_json_value,
)
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import project
from picot.v2.web_ui import MAX_WEB_VIEW_CHARACTERS, WebViewStore, build_web_view


def test_7200_candidates_keep_replay_input_and_every_decision(tmp_path):
    run = large_market_run(tmp_path, 7200)
    snapshot = run.planning_input
    offered = []
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl", evidence_offer=offered.append)
    history.record(bundle=PlanningInputBundle(
        snapshot, (), (), snapshot.captured_at, snapshot.captured_at), run=run)
    record = json.loads(history.path.read_text())
    assert "poll" in record, "oversized comparison must not discard replay inputs"
    # Decode the explicitly versioned archive when the normal JSON exceeds its budget.
    from picot.v2.comparison_archive import expand_comparison_record

    expanded = expand_comparison_record(record)
    assert expanded == json.loads(offered[0])
    poll = expanded["poll"]
    assert len(poll["outcomes"]["canonical_outcomes"]) == 7200
    assert len(poll["outcomes"]["market_revision_evidence"]) == 7200
    assert poll["evaluation"] == json.loads(json.dumps(
        asdict(run.evaluation), default=_record_json_value))
    assert poll["planning_input"]["snapshot_id"] == snapshot.snapshot_id
    assert len(poll["candidate_set"]["energy_paths"]) == 2
    print(f"7200 candidates: diagnostic {history.path.stat().st_size} bytes; lossless roundtrip")
    expected_basic = _basic_incident_record(expanded)
    history._compact_expired_details(snapshot.captured_at + timedelta(hours=40))
    aged = json.loads(history.path.read_text())
    assert aged == expected_basic
    assert aged["decision_evidence"]["candidate_count"] == 7200


def test_large_dashboard_keeps_selected_and_incumbent_without_losing_sections(tmp_path):
    run = large_market_run(tmp_path, 7200)
    view = build_web_view(run, project(run))
    store = WebViewStore()
    store.publish(view)
    encoded = store.latest_json()
    assert encoded is not None and len(encoded) < MAX_WEB_VIEW_CHARACTERS
    shown = json.loads(encoded)
    assert shown.get("dashboard_status", {}).get("status") != "details_limited"
    planning = shown["planning_status"]
    comparison = planning["market_revision_comparison"]
    rows = comparison["alternatives"]
    assert len(rows) <= 50
    assert comparison["alternative_count"] == 7200
    assert {run.evaluation.winning_candidate_id, run.evaluation.incumbent_candidate_id} <= {
        row["candidate_id"] for row in rows}
    assert {row["variant"] for row in rows} == {"retained", "shortened", "removed"}
    dictionary = comparison["evidence_dictionary"]
    expected = {e.candidate_id: list(e.evidence_ids)
                for e in run.outcomes.market_revision_evidence}
    for row in rows:
        entry = dictionary[row["evidence_ids_ref"]]
        if "ids" in entry:
            evidence = entry["ids"]
        else:
            base = dictionary[entry["base"]]["ids"]
            evidence = base[:entry["prefix_count"]]+entry["middle"]+base[entry["suffix_start"]:]
        assert evidence == expected[row["candidate_id"]]
    assert planning["chosen_plan"] == view["planning_status"]["chosen_plan"]
    assert planning["decision"] == view["planning_status"]["decision"]
    assert "plan_explanation" in shown and "soc_timeline" in planning
    assert len(view["planning_status"]["market_revision_comparison"]["alternatives"]) == 7200
    store.publish(shown)
    assert json.loads(store.latest_json())["planning_status"]["market_revision_comparison"] == (
        comparison)
    print(f"7200 candidates: dashboard {len(encoded)} characters; {len(rows)} shown")
