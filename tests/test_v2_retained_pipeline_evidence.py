"""Retained plans remain executable without inventing a fresh evaluation."""

from dataclasses import asdict, replace

import pytest
from test_daily_main_active_pipeline import setup

from picot.v2.projection import project
from picot.v2.web_ui import build_web_view, pipeline_result_nl, pipeline_stage_health


def test_daily_evaluation_preserves_complete_canonical_evidence(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    evidence = first.evaluation.canonical_record
    assert evidence is not None
    assert evidence.evaluation_id == first.evaluation.evaluation_id
    assert evidence.snapshot_id == first.planning_input.snapshot_id
    assert evidence.candidate_set_reference == first.candidate_set.candidate_set_id
    assert evidence.candidate_set_reference == first.outcomes.candidate_set_id
    assert evidence.winning_candidate_id == first.evaluation.winning_candidate_id
    with pytest.raises(ValueError, match="preserve canonical record identity"):
        replace(first.evaluation, candidate_set_id="different-set")
    assert evidence.objective_comparisons
    assert evidence.strategy_version > 0
    serialized = asdict(first.evaluation)["canonical_record"]
    assert serialized == asdict(evidence)
    assert "tie_breaks" in serialized
    assert "invalid_candidates" in serialized
    second = pipeline.run(planning_input=recover())
    assert second.evaluation.canonical_record is None
    assert second.evaluation.evaluation_id != evidence.evaluation_id
    assert second.execution_plan_set.plans[0].evaluation_id == evidence.evaluation_id


def test_retained_pipeline_reports_existing_plan_without_blocking(tmp_path, monkeypatch):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    retained = pipeline.run(planning_input=recover())
    projection = project(retained)
    assert retained.evaluation.winning_candidate_id is None
    builder = projection.cards[4]
    assert builder.state == "plan_retained"
    assert builder.attributes["plan_count"] == 1
    assert retained.execution_plan_set.plans == first.execution_plan_set.plans
    view = build_web_view(retained, projection)
    assert view["pipeline"][3]["result_nl"] == (
        "Het bestaande plan is behouden; er is geen nieuwe winnaar gekozen."
    )
    assert view["pipeline"][4]["result_nl"] == "Het bestaande uitvoeringsplan is behouden."
    assert "werkt correct" not in view["pipeline_health"]["summary_nl"]


def test_real_builder_block_and_already_active_have_distinct_meanings():
    assert pipeline_result_nl(
        stage=4, state="plan_retained", attributes={"winning_candidate_id": "incumbent"},
    ) == "Het bestaande plan is na vergelijking behouden."
    assert pipeline_stage_health(stage=5, state="blocked", attributes={"plan_count": 0}) == "fault"
    assert pipeline_stage_health(
        stage=7, state="blocked", attributes={"blockers": ["manual_override_active"]},
    ) == "healthy"
    assert pipeline_result_nl(stage=7, state="already_active", attributes={}) == (
        "De teruggelezen modus komt al overeen; er is geen nieuwe opdracht nodig."
    )


def test_projected_segments_preserve_canonical_execution_constraints(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    projected = run.execution_plan_set.plans[0]
    canonical = store.load_active_daily_main_plan(projected.execution_scope_id)
    assert any(segment.soc_constraint is not None for segment in canonical.segments)
    for original, shown in zip(canonical.segments, projected.segments, strict=True):
        assert shown.soc_constraint == original.soc_constraint
        assert shown.energy_profile_id == original.energy_profile_id


@pytest.mark.parametrize(
    "status", ("already_active", "awaiting_mode_feedback", "mode_feedback_timeout"),
)
def test_vendor_feedback_identifies_selector_and_timeout(tmp_path, monkeypatch, status):
    _, pipeline, recover = setup(tmp_path, monkeypatch)
    run = pipeline.run(planning_input=recover())
    run = replace(
        run,
        primitive_boundary=replace(run.primitive_boundary, source_entity_id="input_select.mode"),
        vendor_result=replace(run.vendor_result, status=status),
    )
    card = project(run).cards[8]
    assert card.attributes["feedback_source"] == "home_assistant_mode_selector"
    assert card.attributes["physical_confirmation"] == "not_observed"
    assert card.attributes["source_entity_id"] == "input_select.mode"
    assert "HA-keuzestand" in card.attributes["normal_result"]
    view = build_web_view(run, project(run))
    vendor = view["pipeline"][8]
    assert vendor["health"] == ("fault" if status == "mode_feedback_timeout" else "healthy")
    if status == "mode_feedback_timeout":
        assert "niet binnen de wachttijd" in vendor["result_nl"]
        assert not view["pipeline_health"]["healthy"]


def test_grid_duration_decision_is_explained_as_grid_charging_only():
    assert pipeline_result_nl(
        stage=4, state="winner_selected",
        attributes={"decisive_step": "tie_break:grid_charge_duration"},
    ) == "Bij gelijke kosten is het haalbare plan met de kortste netlaadduur gekozen."
