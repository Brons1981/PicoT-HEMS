from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as N

import pytest

from picot.v2.standby_explanation import standby_comparison


def evidence():
    start = datetime(2026, 10, 31, 19, tzinfo=UTC)
    end = start + timedelta(hours=2)

    def path(identity, primitive):
        segment = N(starts_at=start, ends_at=end, execution_scope_id="battery",
                    primitive=N(value=primitive), requested_power_w=None,
                    charge_source_policy=None, soc_constraint=None)
        return N(path_id=identity, horizon_start=start, horizon_end=end,
                 projected_states=[N(at=end, storage_energy_wh=5000)], segments=(segment,))

    active, other = path("active", "standby"), path("other", "balance_bidirectional")
    run = N(candidate_set=N(candidates=[N(candidate_id="a", energy_path_id="active"),
                                       N(candidate_id="b", energy_path_id="other")],
                            energy_paths=[active, other]),
            execution_plan_set=N(plans=[N(winning_energy_path_id="active")]))
    decision = dict(status="retained", incumbent_candidate_id="a", alternative_candidate_id="b",
                    incumbent_cost_eur=1.9, alternative_cost_eur=2.1)
    return run, decision


def test_only_standby_vs_support_with_same_terminal_energy_gets_total_benefit():
    run, decision = evidence()
    result = standby_comparison(run, decision)
    assert result["benefit_eur"] == pytest.approx(0.2)
    assert result["starts_at"] == "2026-10-31T19:00:00+00:00"


def test_replacement_uses_opposite_cost_direction():
    run, decision = evidence()
    decision.update(status="replaced", incumbent_candidate_id="b", alternative_candidate_id="a",
                    incumbent_cost_eur=2.1, alternative_cost_eur=1.9)
    assert standby_comparison(run, decision)["benefit_eur"] == pytest.approx(0.2)


@pytest.mark.parametrize("case", ["stock", "different_action", "no_cost", "wrong_identity",
                                  "more_expensive", "unpublished"])
def test_unproven_attribution_is_suppressed(case):
    run, decision = evidence()
    if case == "stock":
        run.candidate_set.energy_paths[1].projected_states[0].storage_energy_wh = 4000
    elif case == "different_action":
        run.candidate_set.energy_paths[1].segments[0].primitive.value = "charge_at_power"
    elif case == "no_cost":
        decision["incumbent_cost_eur"] = None
    elif case == "wrong_identity":
        run.execution_plan_set.plans[0].winning_energy_path_id = "unrelated"
    elif case == "more_expensive":
        decision["incumbent_cost_eur"] = 3.0
    else:
        decision["status"] = "publication_failed"
    assert standby_comparison(run, decision) is None


def test_explicit_support_baseline_works_without_incumbent_cost_comparison():
    from picot.domain.evaluation import CandidateValidity, ComparisonDirection
    from picot.domain.objectives import ObjectiveKind
    run, _ = evidence()
    def outcome(candidate, cost, baseline=False):
        return N(candidate_id=candidate, validity=CandidateValidity.VALID,
                 objective_outcomes=(N(objective=ObjectiveKind.FINANCIAL_RESULT,
                    unit="EUR", direction=ComparisonDirection.HIGHER_IS_BETTER,
                    value=-cost,
                    evidence_ids=("bridge-economic-support:fixture",) if baseline else ()),))
    run.execution_plan_set.plans[0].winning_candidate_id = "a"
    run.outcomes = N(canonical_outcomes=(outcome("a", 1.9), outcome("b", 2.1, True)))
    result = standby_comparison(run, {"status": "selected"})
    assert result["benefit_eur"] == pytest.approx(0.2)
    assert result["comparison_basis"] == "normal_support_then_refill"
    run.candidate_set.energy_paths[1].projected_states[0].storage_energy_wh = 4000
    assert standby_comparison(run, {"status": "selected"}) is None


def usage_evidence():
    from picot.domain.energy_path import ProjectedEnergyState
    run, decision = evidence()
    path = run.candidate_set.energy_paths[0]
    start, end = path.horizon_start, path.horizon_end
    middle = start + timedelta(hours=1)
    path.projected_states = [
        ProjectedEnergyState(at=middle, confidence=1, flow_starts_at=start,
            household_demand_wh=1000, pv_household_wh=200, grid_household_wh=800,
            grid_storage_input_wh=0, grid_import_cost_eur=0.24, pv_other_wh=700),
        ProjectedEnergyState(at=end, confidence=1, flow_starts_at=middle,
            household_demand_wh=500, pv_household_wh=0, grid_household_wh=500,
            grid_storage_input_wh=0, grid_import_cost_eur=0.20, storage_energy_wh=5000),
    ]
    return run, decision


def test_standby_usage_reports_household_solar_not_all_pv_and_interval_costs():
    run, decision = usage_evidence()
    usage = standby_comparison(run, decision)['usage']
    assert usage == pytest.approx(dict(household_kwh=1.5, solar_used_kwh=0.2,
                                      grid_kwh=1.3, grid_cost_eur=0.44))


@pytest.mark.parametrize('case', ['missing', 'gap', 'overlap', 'partial', 'charging'])
def test_incomplete_standby_usage_is_not_reported_as_zero(case):
    from dataclasses import replace
    run, decision = usage_evidence()
    path = run.candidate_set.energy_paths[0]
    first = path.projected_states[0]
    if case == 'missing':
        first = replace(first, pv_household_wh=None)
    elif case == 'gap':
        first = replace(first, flow_starts_at=first.flow_starts_at + timedelta(minutes=15))
    elif case == 'overlap':
        first = replace(first, at=first.at + timedelta(minutes=15))
    elif case == 'partial':
        first = replace(first, flow_starts_at=first.flow_starts_at - timedelta(minutes=15))
    else:
        first = replace(first, grid_storage_input_wh=100)
    path.projected_states[0] = first
    result = standby_comparison(run, decision)
    assert result['benefit_eur'] == pytest.approx(0.2)
    assert 'usage' not in result


def test_standby_usage_preserves_negative_tariff_cost_and_true_zero_solar():
    from dataclasses import replace
    run, decision = usage_evidence()
    path = run.candidate_set.energy_paths[0]
    path.projected_states[0] = replace(path.projected_states[0],
        household_demand_wh=800, pv_household_wh=0, grid_import_cost_eur=-0.30)
    usage = standby_comparison(run, decision)['usage']
    assert usage['solar_used_kwh'] == 0
    assert usage['grid_cost_eur'] == pytest.approx(-0.10)
