from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup
from test_main_revision_total_cost import revision
from test_plan_narrative_dashboard import narrative, narrative_text

from picot.v2.plan_narrative import build_plan_narrative


def test_active_route_has_cash_projection_without_comparable_alternative(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    cost = build_plan_narrative(run)["cost_projection"]
    assert cost["total_cost_eur"] == cost["import_cost_eur"] - cost["export_revenue_eur"]
    assert cost["starts_at"] == run.planning_input.captured_at.isoformat()
    assert cost["import_cost_eur"] > 0
    # A later observation has no new projection; the identity-bound display cache
    # may preserve the previous calculation, but must not invent a fresh one.
    assert build_plan_narrative(pipeline.run(planning_input=recover()))["cost_projection"] is None
    fallback = replace(run, evaluation=replace(run.evaluation, status="fallback_active"))
    assert build_plan_narrative(fallback)["cost_projection"] is None


def test_cost_display_is_separate_from_savings_and_has_exact_period():
    cost = {"starts_at": "2026-11-01T07:07:00Z", "ends_at": "2026-11-01T23:00:00Z",
            "import_cost_eur": 9.0, "export_revenue_eur": 1.25, "total_cost_eur": 7.75}
    text = narrative_text(narrative(cost_projection=cost), at="2026-11-01T07:10:00Z")
    assert "7,75" in text and "9,00" in text and "1,25" in text
    assert "08:07" in text and "00:00" in text
    assert "besparing" not in text
    assert "7,75" not in narrative_text(narrative(cost_projection=cost),
                                        at="2026-11-02T01:00:00Z")


def test_soc_repair_reports_full_cash_not_acquisition_rate():
    portfolio, result = revision(20, 0, invalid=("daily_main_goal_unreachable",))
    source = next(s for s in portfolio.sources
                  if s.candidate_id == result.record.winning_candidate_id)
    candidate = next(c for c in portfolio.candidate_set.candidates
                     if c.candidate_id == source.candidate_id)
    path = next(p for p in portfolio.candidate_set.energy_paths
                if p.path_id == candidate.energy_path_id)
    assert path.projected_import_cost_eur - path.projected_export_revenue_eur == pytest.approx(
        -source.financial.cash_result_eur)
    outcome = next(o for o in portfolio.outcome_set.outcomes
                   if o.candidate_id == source.candidate_id)
    assert outcome.objective_outcomes[0].unit == "EUR/kWh-stored"


def test_cost_survives_observation_and_restart_only_for_same_plan(tmp_path, monkeypatch):
    from picot.v2.plan_decision_cache import PlanDecisionCache
    from picot.v2.web_ui import _build_planning_status

    _, pipeline, recover = setup(tmp_path, monkeypatch)
    first = _build_planning_status(pipeline.run(planning_input=recover()))
    path = tmp_path / "display.json"
    PlanDecisionCache(path).apply(first)
    observed = _build_planning_status(pipeline.run(planning_input=recover()))
    restored = PlanDecisionCache(path).apply(observed)
    original = first["plan_decision"]["narrative"]
    assert restored["plan_decision"]["narrative"]["cost_projection"] == original["cost_projection"]
    assert restored["plan_decision"]["narrative"]["projected_at"] == original["projected_at"]
    changed = {**observed, "execution_plans": [{"plan_id": "new", "energy_path_id": "new"}]}
    replacement = PlanDecisionCache(path).apply(changed)
    assert replacement["plan_decision"]["narrative"]["cost_projection"] is None


def test_missing_nonfinite_and_other_snapshot_cost_is_not_shown(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    for changes in ({"projected_import_cost_eur": None},
                    {"projected_export_revenue_eur": float("nan")},
                    {"snapshot_id": "old-snapshot"}):
        paths = tuple(replace(p, **changes) for p in run.candidate_set.energy_paths)
        changed = replace(run, candidate_set=replace(run.candidate_set, energy_paths=paths))
        assert build_plan_narrative(changed)["cost_projection"] is None
