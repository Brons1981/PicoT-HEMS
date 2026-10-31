from dataclasses import replace

from test_daily_main_active_pipeline import setup

from picot.domain.evaluation import (
    ComparisonDirection,
    InvalidCandidateRecord,
    ObjectiveOutcome,
)
from picot.domain.objectives import ObjectiveKind
from picot.v2.plan_decision_explanation import build_plan_decision


def test_initial_acquisition_is_not_presented_as_total_savings(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    explanation = build_plan_decision(run)
    assert explanation["status"] == "selected"
    assert explanation["incumbent_cost_eur"] is None
    assert "opgeslagen kWh" in explanation["reason"]
    assert "Geen afzonderlijke toekomstige autolaadsessie" in explanation["ev_assumption"]


def test_total_comparison_uses_canonical_costs_and_signed_benefit(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    winner = run.evaluation.winning_candidate_id
    # Projection contract: the existing canonical evaluator owns validity and
    # the winner. Deliberately supply a financially worse challenger.
    outcomes = tuple(replace(o, objective_outcomes=(ObjectiveOutcome(
        ObjectiveKind.FINANCIAL_RESULT, -1.98 if o.candidate_id == winner else -2.14,
        ComparisonDirection.HIGHER_IS_BETTER, "EUR", 1.0,
    ),), commitment_improvement_eur=0.0 if o.candidate_id == winner else -0.16)
        for o in run.outcomes.canonical_outcomes)
    run = replace(run, outcomes=replace(run.outcomes, canonical_outcomes=outcomes),
        evaluation=replace(run.evaluation, incumbent_candidate_id=winner,
                           status="plan_retained"))
    result = build_plan_decision(run)
    assert result["status"] == "retained"
    assert result["incumbent_cost_eur"] == 1.98
    assert result["alternative_cost_eur"] == 2.14
    assert result["improvement_eur"] == -0.16
    assert result["horizon_start"] == run.planning_input.captured_at.isoformat()
    assert result["horizon_end"] is not None


def test_failed_publication_does_not_explain_challenger_as_active(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    plans = tuple(replace(p, winning_candidate_id="previous-winner")
                  for p in run.execution_plan_set.plans)
    run = replace(run, execution_plan_set=replace(run.execution_plan_set, plans=plans),
                  evaluation=replace(run.evaluation, status="plan_retained",
                                     reason="store_write_failed"))
    result = build_plan_decision(run)
    assert result["status"] == "publication_failed"
    assert "store_write_failed" in result["reason"]
    assert result["improvement_eur"] is None


def test_normal_tick_is_explicitly_not_a_new_comparison(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover())
    run = pipeline.run(planning_input=recover())
    result = build_plan_decision(run)
    assert result["source"] == "observation"
    assert result["status"] == "retained"
    assert result["improvement_eur"] is None


def test_fallback_never_claims_selected_plan(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    run = replace(run, evaluation=replace(run.evaluation, status="fallback_active",
                                         reason="missing_prices"))
    result = build_plan_decision(run)
    assert result["status"] == "fallback"
    assert "missing_prices" in result["reason"]
    assert result["improvement_eur"] is None


def test_unequal_stock_exclusion_is_explained_without_invented_savings(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    record = replace(run.evaluation.canonical_record, invalid_candidates=(
        InvalidCandidateRecord("excluded-alternative", (
            "main_revision_terminal_inventory_not_equal",)),))
    run = replace(run, evaluation=replace(run.evaluation, canonical_record=record))
    result = build_plan_decision(run)
    assert "andere eindvoorraad" in result["reason"]
    assert result["improvement_eur"] is None
