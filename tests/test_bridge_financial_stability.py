"""One-cent route equivalence must not introduce relay switching."""
from dataclasses import replace

import pytest
from test_evaluation_engine import BASE, _candidate_set, _outcome, _outcome_set, _strategy

from picot.domain.evaluation import CandidateValidity
from picot.planner.evaluation_engine import EvaluationEngine


def evaluate(benefit, *, incumbent="candidate-a", invalid=False, stable=True):
    candidates = _candidate_set()
    a = replace(_outcome("candidate-a", 1.0, 1000), expected_switching_count=2,
                validity=CandidateValidity.INVALID if invalid else CandidateValidity.VALID,
                invalidity_reasons=("daily_main_goal_unreachable",) if invalid else ())
    b = replace(_outcome("candidate-b", 1.0 + benefit, 2000), expected_switching_count=4)
    return EvaluationEngine().evaluate(
        candidates, _strategy(), replace(_outcome_set(candidates), outcomes=(a, b)),
        created_at=BASE, incumbent_candidate_id=incumbent,
        financial_equivalence_margin=0.01 if stable else 0.0,
        prefer_financial_stability=stable,
    )


@pytest.mark.parametrize("benefit", [0.0000305167, 0.0000808136, 0.009])
def test_existing_valid_route_survives_subcent_benefit(benefit):
    result = evaluate(benefit)
    assert result.record.winning_candidate_id == "candidate-a"
    assert result.record.decisive_step == "commitment:equivalent_incumbent_retained"


def test_new_equivalent_routes_prefer_fewer_switches_before_secondary_objectives():
    result = evaluate(0.009, incumbent=None)
    assert result.record.winning_candidate_id == "candidate-a"
    assert result.record.decisive_step == "tie_break:expected_switching_count"


@pytest.mark.parametrize("benefit", [0.01, 0.011])
def test_meaningful_saving_still_wins(benefit):
    assert evaluate(benefit).record.winning_candidate_id == "candidate-b"


def test_invalid_incumbent_cannot_block_necessary_repair():
    assert evaluate(-0.02, invalid=True).record.winning_candidate_id == "candidate-b"


def test_other_comparisons_keep_existing_selection():
    assert evaluate(0.0000305167, stable=False).record.winning_candidate_id == "candidate-b"


def test_baseline_is_not_incumbent_when_actual_charge_command_differs(tmp_path, monkeypatch):
    from test_daily_bridge_pipeline import started
    from test_daily_main_charge_windows import inputs

    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

    _, _, recover, source, _, _ = started(tmp_path, monkeypatch)
    snapshot = recover(source)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    assessment = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion)
    windows = adapter.bridge_windows(snapshot=snapshot, trigger=assessment.trigger,
                                     conversion_model=conversion)
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.windows[0].schedule.horizon_end)
    def produce(observation):
        return produce_main_charge_portfolio(
            snapshot=observation, windows=windows, tariffs=tariffs, opportunity_ids=())
    assert produce(snapshot).incumbent_candidate_id is not None
    context = snapshot.daily_charge_context
    changed = replace(snapshot, daily_charge_context=replace(context, main_plans=tuple(
        replace(plan, segments=tuple(
            replace(segment, requested_power_w=1000)
            if segment.primitive is ExecutionPrimitive.CHARGE_AT_POWER else segment
            for segment in plan.segments))
        if plan.plan_id in context.active_main_plan_ids else plan for plan in context.main_plans)))
    assert produce(changed).incumbent_candidate_id is None
