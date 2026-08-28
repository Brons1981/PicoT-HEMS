from dataclasses import replace
from datetime import timedelta
from importlib import import_module

from test_v2_delegated_storage_pipeline_integration import BASE, _snapshot

from picot.v2.contracts import PriceForecastPoint
from picot.v2.opportunity_engine import PriceOpportunityConfig
from legacy_cp_pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.web_ui import build_web_view, pipeline_result_nl


def _price_point(index: int, value: float) -> PriceForecastPoint:
    starts_at = BASE + timedelta(minutes=15 * index)
    return PriceForecastPoint(
        point_id=f"price-{index}",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=15),
        value_eur_per_kwh=value,
        confidence=0.9,
        evidence_id="price-forecast",
    )


def test_stage_five_summary_uses_the_projected_plan_count() -> None:
    assert pipeline_result_nl(
        stage=5,
        state="observer_only",
        attributes={"plan_count": 1},
    ) == "Er is 1 uitvoeringsplan voorbereid."


def test_web_view_explains_energy_opportunities_by_kind_in_plain_dutch() -> None:
    planning_input = replace(
        _snapshot(),
        price_points=(
            _price_point(0, 0.10),
            _price_point(1, 0.11),
            _price_point(2, 0.30),
            _price_point(3, 0.29),
        ),
    )
    run = CanonicalPipeline().run(
        planning_input=planning_input,
        price_opportunity_config=PriceOpportunityConfig(
            low_price_margin_eur_per_kwh=0.02,
            high_price_margin_eur_per_kwh=0.0,
            config_version="plain-language-test:v1",
        ),
    )

    explanation = build_web_view(run, project(run))["plan_explanation"]

    assert explanation["title"] == "Wat PicoT overweegt"
    assert explanation["opportunity_count"] == len(run.opportunities.opportunities)
    assert explanation["opportunity_groups"]
    for group in explanation["opportunity_groups"]:
        assert group["label_nl"]
        assert group["summary_nl"]
        assert group["count"] == len(group["items"])
        for item in group["items"]:
            assert item["period_nl"]
            assert item["price_nl"]
            assert item["confidence_nl"]
            assert item["reason_nl"]
            assert "opportunity-" not in item["summary_nl"]


def test_web_view_compares_plans_and_explains_the_winner_without_ids() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    explanation = build_web_view(run, project(run))["plan_explanation"]

    alternatives = explanation["plans"]
    assert [item["label_nl"] for item in alternatives] == [
        "Niets extra doen",
        "Laden met verwachte zonne-energie",
    ]
    assert sum(item["selected"] for item in alternatives) == 1
    for item in alternatives:
        assert item["period_nl"]
        assert item["energy_nl"]
        assert item["grid_energy_nl"]
        assert item["reason_nl"]

    decision = explanation["decision"]
    assert decision["summary_nl"] == (
        "PicoT kiest laden met verwachte zonne-energie."
    )
    assert "zonder netladen" in decision["reason_nl"]
    assert "candidate-" not in decision["summary_nl"]
    assert "candidate-" not in decision["reason_nl"]


def test_day_planning_exposes_one_run_of_canonical_decision_facts() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    view = build_web_view(run, project(run))
    status = view["planning_status"]

    assert status["run_id"] == run.planning_input.run_id
    assert status["snapshot_id"] == run.planning_input.snapshot_id
    assert status["captured_at"] == run.planning_input.captured_at.isoformat()
    assert status["valid_until"] == run.planning_input.horizon_end.isoformat()
    assert status["decision"] == {
        "status": run.evaluation.status,
        "candidate_family": "pv_charge_only",
        "reason": run.evaluation.reason,
        "decisive_step": run.evaluation.decisive_step,
        "confidence": run.outcomes.outcomes[0].confidence,
    }
    assert status["strategy"]["status"] == "not_available"
    assert status["strategy"]["reason"] == "not_available"
    assert status["storage_target"]["required_energy_wh"] > 0
    assert status["storage_target"]["required_by"]
    assert status["storage_target"]["requirement_satisfied"] is True
    assert status["execution"]["status"] == run.execution_record.status
    assert status["execution"]["reason"] == run.execution_record.reason
    assert status["execution"]["primitive_status"] == run.primitive_boundary.status
    assert len(status["alternatives"]) == len(run.candidate_set.candidates)
    assert sum(item["selected"] for item in status["alternatives"]) == 1


def test_day_planning_dashboard_renders_fact_sections_not_a_merged_sentence() -> None:
    html = import_module("picot.v2.web_ui").DASHBOARD_HTML

    assert "function renderPlanningStatus" in html
    assert 'id="planning-status"' in html
    assert '"Huidige strategie"' in html
    assert '"Besluit"' in html
    assert '"Uitvoering"' in html
    assert '"Geldigheid"' in html


def test_zero_confidence_is_a_visible_readiness_blocker() -> None:
    source = _snapshot()
    low_confidence = replace(
        source,
        current_storage_states=tuple(
            replace(item, confidence=0.0)
            for item in source.current_storage_states
        ),
    )
    run = CanonicalPipeline().run(planning_input=low_confidence)

    readiness = build_web_view(run, project(run))["plan_explanation"]["readiness"]

    assert readiness["confidence_percent"] == 0
    assert readiness["status"] == "blocked"
    assert readiness["warning_nl"] == (
        "De planningszekerheid is 0%; PicoT voert dit plan niet uit."
    )
    assert "planning_confidence_below_minimum" in readiness["blockers"]
    assert run.primitive_boundary.request_id is None


def test_dashboard_renders_the_plain_language_explanation_before_details() -> None:
    html = import_module("picot.v2.web_ui").DASHBOARD_HTML

    assert '<h2>Onderliggende energiekansen</h2>' in html
    assert 'id="plan-explanation"' in html
    assert "function renderPlanExplanation" in html
    assert "renderPlanExplanation(view.plan_explanation)" in html
    assert html.index('id="pipeline"') < html.index('id="plan-explanation"')
