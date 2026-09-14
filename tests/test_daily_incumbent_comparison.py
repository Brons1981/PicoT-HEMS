"""Fresh daily incumbents and grid-only command duration (ADR-037.16)."""

from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_daily_pv_route_optimisation import observed, source_with_later_cheap_window

from picot.domain.daily_reference_charge_window import (
    DailyMainChargeWindow,
    DailyMainChargeWindowSet,
)
from picot.domain.evaluation import CandidateValidity
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.objectives import ObjectiveKind
from picot.planner.evaluation_engine import EvaluationEngine
from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter


def comparison_fixture(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    original = source_with_later_cheap_window()
    first = pipeline.run(planning_input=recover(original))
    source = recover(observed(original, soc=0.9))
    adapter = IndependentDailyReferenceAdapter()
    assessment = adapter.main_charge_incumbent(
        snapshot=source, assignment=store.load_daily_assignments()[0],
        conversion_model=inputs()["conversion_model"],
        horizon_end=first.execution_plan_set.plans[0].valid_until,
    )
    return store, pipeline, recover, source, assessment


def equivalent_window(assessment):
    schedule = replace(assessment.schedule, schedule_id="equivalent-challenger")
    projection = replace(assessment.projection, intent_schedule_id=schedule.schedule_id)
    reached = next(at for i in projection.intervals
                   for at, energy in ((i.starts_at, i.storage_energy_at_start_wh),
                                      (i.ends_at, i.storage_energy_at_end_wh))
                   if energy + 1e-6 >= assessment.target_storage_energy_wh
                   and any(s.starts_at <= at <= s.ends_at for s in assessment.main_segments))
    return DailyMainChargeWindow(
        assessment.assignment_id, assessment.family, schedule, assessment.main_segments,
        projection, reached, assessment.target_storage_energy_wh,
        assessment.retained_main_segments, assessment.supplemental_assignments,
    )


def test_equal_remaining_route_retains_original_plan_identity(tmp_path, monkeypatch):
    store, pipeline, recover, source, assessment = comparison_fixture(tmp_path, monkeypatch)
    original_plan = store.load_active_daily_main_plan("battery")
    original_revision = store.load_daily_assignments()[0].revision
    # Exercise Evaluation's equality decision and the pipeline's retain branch
    # with an otherwise admissible, physically identical challenger.
    window = equivalent_window(assessment)
    windows = DailyMainChargeWindowSet(
        window.assignment_id, source.snapshot_id, (window,), "discovered", "test-equivalent", 1,
    )
    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows",
                        lambda *args, **kwargs: windows)
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.winning_candidate_id == result.evaluation.incumbent_candidate_id
    assert result.evaluation.commitment_decision == "retained"
    assert result.evaluation.decisive_step == "commitment:equivalent_incumbent_retained"
    assert store.load_active_daily_main_plan("battery") == original_plan
    assert store.load_daily_assignments()[0].revision == original_revision
    assert result.execution_plan_set.plans[0].plan_id == original_plan.plan_id
    assert result.evaluation.canonical_record.snapshot_id == source.snapshot_id


@pytest.mark.parametrize("minutes", [60, 65])
def test_high_soc_removes_redundant_grid_duration_with_valid_incumbent(
    tmp_path, monkeypatch, minutes,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    original = source_with_later_cheap_window()
    pipeline.run(planning_input=recover(original))
    result = pipeline.run(planning_input=recover(observed(original, soc=0.9, minutes=minutes)))
    outcomes = {o.candidate_id: o for o in result.outcomes.canonical_outcomes}
    incumbent = outcomes[result.evaluation.incumbent_candidate_id]
    winner = outcomes[result.evaluation.winning_candidate_id]
    assert incumbent.validity is CandidateValidity.VALID
    assert winner.grid_charge_duration_seconds < incumbent.grid_charge_duration_seconds
    assert result.evaluation.commitment_decision == "triggered_revision"
    assert any(t.kind.value == "grid_charge_duration"
               for t in result.evaluation.canonical_record.tie_breaks)
    for path in result.candidate_set.energy_paths:
        outcome = outcomes[next(c.candidate_id for c in result.candidate_set.candidates
                                if c.energy_path_id == path.path_id)]
        assert outcome.grid_charge_duration_seconds == sum(
            (s.ends_at - s.starts_at).total_seconds() for s in path.segments
            if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER
        )


def test_incumbent_financial_outcomes_are_fresh_and_normalized(tmp_path, monkeypatch):
    _, _, _, source, assessment = comparison_fixture(tmp_path, monkeypatch)
    window = equivalent_window(assessment)
    windows = DailyMainChargeWindowSet(
        window.assignment_id, source.snapshot_id, (window,), "discovered", "equivalent", 1,
    )
    tariffs = IndependentDailyTariffAdapter().build(source, horizon_end=window.schedule.horizon_end)
    portfolio = produce_main_charge_portfolio(
        snapshot=source, windows=windows, tariffs=tariffs, opportunity_ids=(), incumbent=assessment,
    )
    prices = [next(v.value for v in o.objective_outcomes
                   if v.objective is ObjectiveKind.FINANCIAL_RESULT)
              for o in portfolio.outcome_set.outcomes]
    assert prices == [0.1, 0.1]
    result = EvaluationEngine().evaluate(
        portfolio.candidate_set, portfolio.strategy, portfolio.outcome_set,
        created_at=source.captured_at, incumbent_candidate_id=portfolio.incumbent_candidate_id,
    )
    assert result.record.winning_candidate_id == portfolio.incumbent_candidate_id

    higher_tariffs = replace(tariffs, intervals=tuple(
        replace(i, import_eur_per_kwh=i.import_eur_per_kwh + 0.000001)
        for i in tariffs.intervals
    ))
    higher = produce_main_charge_portfolio(
        snapshot=source, windows=windows, tariffs=higher_tariffs,
        opportunity_ids=(), incumbent=assessment,
    )
    assert all(next(v.value for v in o.objective_outcomes
                    if v.objective is ObjectiveKind.FINANCIAL_RESULT) == 0.100001
               for o in higher.outcome_set.outcomes)


def test_uncovered_incumbent_horizon_is_explicitly_invalid(tmp_path, monkeypatch):
    from datetime import timedelta

    _, _, _, source, original = comparison_fixture(tmp_path, monkeypatch)
    until = original.plan.valid_until - timedelta(minutes=15)
    shortened = replace(original.plan, valid_until=until, segments=tuple(
        replace(s, ends_at=min(s.ends_at, until))
        for s in original.plan.segments if s.starts_at < until
    ))
    context = source.daily_charge_context
    source = replace(source, daily_charge_context=replace(
        context, main_plans=tuple(shortened if p.plan_id == shortened.plan_id else p
                                  for p in context.main_plans),
    ))
    assessment = IndependentDailyReferenceAdapter().main_charge_incumbent(
        snapshot=source, assignment=context.assignments[0],
        conversion_model=inputs()["conversion_model"], horizon_end=original.plan.valid_until,
    )
    assert "incumbent_remaining_horizon_not_covered" in assessment.invalidity_reasons
    assert "incumbent_remaining_schedule_gap" in assessment.invalidity_reasons


def test_reinterpreted_schedule_cannot_validate_original_incumbent(tmp_path, monkeypatch):
    from picot.domain.daily_reference_intent import DailyStorageIntent

    _, _, _, source, original = comparison_fixture(tmp_path, monkeypatch)
    adapter = IndependentDailyReferenceAdapter()
    retained = adapter._retained_main_schedule

    def reconciled(**kwargs):
        schedule, origins = retained(**kwargs)
        schedule = replace(schedule, intervals=tuple(
            replace(i, intent=DailyStorageIntent.NOM)
            if i.intent is DailyStorageIntent.GRID_REQUIREMENT else i
            for i in schedule.intervals
        ))
        return schedule, origins

    monkeypatch.setattr(adapter, "_retained_main_schedule", reconciled)
    assessment = adapter.main_charge_incumbent(
        snapshot=source, assignment=source.daily_charge_context.assignments[0],
        conversion_model=inputs()["conversion_model"], horizon_end=original.plan.valid_until,
    )
    assert "incumbent_schedule_requires_reconciliation" in assessment.invalidity_reasons
