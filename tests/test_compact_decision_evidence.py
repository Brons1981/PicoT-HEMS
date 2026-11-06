"""Oversized decisions retain monetary comparisons rather than only a winner ID."""

import json
from datetime import UTC, datetime, timedelta

import picot.v2.planning_incident_history as module
from picot.v2.diagnostic_downloads import incident_overview
from picot.v2.planning_incident_history import PlanningIncidentHistory


def record():
    return dict(event="planning_outcome_changed", poll=dict(
        captured_at_utc=datetime.now(UTC).isoformat(), run_id="run-proof",
        snapshot_id="snapshot-proof", planning_input={"large": "x" * 20000},
        evaluation=dict(status="winner_selected", evaluation_id="evaluation-proof",
            winning_candidate_id="winner", incumbent_candidate_id="old",
            reason="objective:financial_result", decisive_step="objective:financial_result",
            financial_equivalence_margin_eur=0.01,
            evaluated_candidate_ids=["old", "winner", "invalid"],
            canonical_record=dict(strategic_objective_order=["financial_result"],
                objective_comparisons=[dict(objective="financial_result", unit="EUR",
                    direction="higher_is_better", equivalence_margin=0.01, decisive=True,
                    values=[dict(candidate_id="old", value=-1.2, result="worse"),
                            dict(candidate_id="winner", value=-1.0, result="equal")],
                    retained_candidate_ids=["winner"])], tie_breaks=[])),
        outcomes=dict(outcomes=[
            dict(candidate_id="old", validity="valid", invalidity_reasons=[],
                 worst_case_financial_result_eur=-1.2, expected_switching_count=2),
            dict(candidate_id="winner", validity="valid", invalidity_reasons=[],
                 worst_case_financial_result_eur=-1.0, expected_switching_count=3),
            dict(candidate_id="invalid", validity="invalid",
                 invalidity_reasons=["reserve_shortfall"], worst_case_financial_result_eur=None),
        ]), execution_plan_set={"plans": []}))


def test_oversized_decision_preserves_costs_validity_and_policy_in_download(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_INCIDENT_RECORD_BYTES", 10000)
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    original = record()
    history._append(original)
    saved = json.loads(history.path.read_text())
    evidence = saved["decision_evidence"]
    assert evidence["complete"]
    assert evidence["evaluation"]["financial_equivalence_margin_eur"] == 0.01
    rows = {r["candidate_id"]: r for r in evidence["candidates"]}
    assert rows["old"]["outcome"]["worst_case_financial_result_eur"] == -1.2
    assert rows["winner"]["outcome"]["worst_case_financial_result_eur"] == -1.0
    assert rows["invalid"]["outcome"]["invalidity_reasons"] == ["reserve_shortfall"]
    assert rows["old"]["comparisons"][0]["value"] == -1.2
    assert evidence["objective_comparisons"][0]["direction"] == "higher_is_better"
    assert incident_overview(history.path)[0]["decision_evidence"] == evidence
    # Retention compaction must not erase an already bounded decision.
    history._compact_expired_details(datetime.now(UTC) + timedelta(hours=40))
    aged = json.loads(history.path.read_text())
    assert aged["run_id"] == "run-proof"
    assert aged["decision_evidence"] == evidence
    assert len(history.path.read_bytes()) < 10000


def test_candidate_cap_is_explicit_and_prioritises_winner_and_incumbent(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_INCIDENT_RECORD_BYTES", 10000)
    monkeypatch.setattr(module, "MAX_DECISION_CANDIDATES", 2)
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    history._append(record())
    evidence = json.loads(history.path.read_text())["decision_evidence"]
    assert not evidence["complete"]
    assert evidence["candidate_count"] == 3
    assert evidence["omitted_candidate_count"] == 1
    assert [r["candidate_id"] for r in evidence["candidates"]] == ["winner", "old"]


def test_byte_budget_reports_omissions_without_losing_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_INCIDENT_RECORD_BYTES", 10000)
    monkeypatch.setattr(module, "MAX_DECISION_EVIDENCE_BYTES", 4096)
    value = record()
    value["poll"]["outcomes"]["outcomes"].extend(
        dict(candidate_id=f"other-{i}", validity="invalid",
             invalidity_reasons=["x" * 2000], worst_case_financial_result_eur=None)
        for i in range(100)
    )
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    history._append(value)
    evidence = json.loads(history.path.read_text())["decision_evidence"]
    assert len(json.dumps(evidence).encode()) < 4096
    assert not evidence["complete"]
    assert evidence["omitted_candidate_count"] > 0
    assert [r["candidate_id"] for r in evidence["candidates"][:2]] == ["winner", "old"]


def test_real_canonical_market_outcomes_survive_size_reduction(tmp_path, monkeypatch):
    from test_market_revision_incident_history import large_market_run

    from picot.v2.planning_input import PlanningInputBundle

    run = large_market_run(tmp_path, 3)
    monkeypatch.setattr(module, "MAX_INCIDENT_RECORD_BYTES", 50000)
    history = PlanningIncidentHistory(tmp_path / "incidents.jsonl")
    source = run.planning_input
    bundle = PlanningInputBundle(source, (), (), source.captured_at, source.captured_at)
    history.record(bundle=bundle, run=run)
    saved = json.loads(history.path.read_text())
    assert saved["detail_level"] == "bounded"
    evidence = saved["decision_evidence"]
    assert evidence["complete"]
    rows = {r["candidate_id"]: r for r in evidence["candidates"]}
    for outcome in run.outcomes.canonical_outcomes:
        row = rows[outcome.candidate_id]
        assert row["outcome"]["validity"] == outcome.validity
        assert row["outcome"]["invalidity_reasons"] == list(outcome.invalidity_reasons)
        assert row["objectives"][0]["value"] == outcome.objective_outcomes[0].value
        assert row["comparisons"][0]["value"] == outcome.objective_outcomes[0].value
