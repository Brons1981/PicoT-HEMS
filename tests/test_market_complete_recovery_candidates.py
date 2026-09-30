"""A cheap partial charge decision must not erase complete market alternatives."""

from dataclasses import replace

import pytest
from test_daily_main_active_pipeline import setup
from test_daily_main_charge_windows import inputs
from test_market_rule_selection import winter_source

from picot.domain.capability_snapshot import CapabilityAvailability
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.market_daily_assignment import MarketDailyAssignment
from picot.planner.evaluation_engine import EvaluationEngine
from picot.v2 import market_rule_planning


def complete_recovery_fixture(tmp_path, monkeypatch, *, household_energy_wh=0):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    source = winter_source(recover())
    if household_energy_wh:
        source = replace(source, household_load_forecast=replace(
            source.household_load_forecast, intervals=tuple(
                replace(i, expected_energy_wh=household_energy_wh)
                for i in source.household_load_forecast.intervals
            ),
        ))
    first = pipeline.run(planning_input=recover(source))
    assert first.execution_plan_set.plans
    pipeline.run(planning_input=recover(source))
    plan = store.load_active_daily_main_plan("battery")
    # Today's goal is already full; tomorrow owns recovery after today's export.
    # Complete trade/recovery combinations must still reach final Evaluation.
    snapshot = recover(replace(source, price_points=tuple(
        replace(p, value_eur_per_kwh=0.001) if p.starts_at.hour == 14 else p
        for p in source.price_points
    )))
    today = next(a for a in snapshot.daily_charge_context.assignments
                 if a.delivery_date == snapshot.captured_at.date())
    day = max(snapshot.daily_charge_context.assignments, key=lambda a: a.delivery_date)
    assignment = MarketDailyAssignment(
        snapshot.market_user_rule, "battery", today.delivery_date, today.timezone,
        snapshot.captured_at, snapshot.current_storage_states[0].usable_capacity_wh,
    )
    actual_export_windows = market_rule_planning.export_windows

    def one_real_export_window(*args, **kwargs):
        generated = actual_export_windows(*args, **kwargs)
        return (next(w for w in generated if w[0].starts_at.hour == 15
                     and w[0].starts_at.minute == 0),)

    monkeypatch.setattr(market_rule_planning, "export_windows", one_real_export_window)
    return snapshot, plan, assignment, day


def test_all_complete_recovery_routes_reach_final_market_evaluation(tmp_path, monkeypatch):
    snapshot, plan, assignment, day = complete_recovery_fixture(tmp_path, monkeypatch)
    market = market_rule_planning.market_rule_portfolio(
        snapshot=snapshot, plan=plan, assignment=assignment,
        conversion=inputs()["conversion_model"], opportunity_ids=(),
    )
    assert len(market.comparable.candidate_set.candidates) > 1, market.reasons
    assert len({c.candidate_id for c in market.comparable.candidate_set.candidates}) == len(
        market.evidence)
    assert all(len(e.source_ids) >= 2 for e in market.comparable.candidate_set.exclusions)
    for evidence in market.evidence:
        assert evidence.admission.status == "admissible"
        assert evidence.admission.expected_export_wh == pytest.approx(816)
        assert evidence.admission.incremental_net_profit_eur > 0
        assert evidence.charge_window.assignment_id == day.assignment_id
        assert evidence.charge_trigger.assignment_id == day.assignment_id
        projection = evidence.charge_window.projection
        assert min(min(i.storage_energy_at_start_wh, i.storage_energy_at_end_wh)
                   for i in projection.intervals) >= 816
        recovery_stock = next(i.storage_energy_at_end_wh for i in projection.intervals
                              if i.ends_at == evidence.admission.recovery_ends_at)
        assert recovery_stock == pytest.approx(8160)
    result = EvaluationEngine().evaluate(
        market.comparable.candidate_set, market.comparable.strategy,
        market.comparable.outcome_set, created_at=snapshot.captured_at,
    )
    selected = next(e for e in market.evidence
                    if e.candidate_id == result.record.winning_candidate_id)
    assert selected.admission.incremental_net_profit_eur == max(
        e.admission.incremental_net_profit_eur for e in market.evidence)
    assert selected.admission.recovery_ends_at.date() == day.delivery_date
    # 816 Wh sold at .80, restored at .001; ideal conversion in this fixture.
    # Supplier addition is not returned; export addition is .02, tax is netted.
    expected = 0.816 * (0.8 - 0.01653 * 1.21 + 0.02 - 0.001)
    assert selected.admission.incremental_net_profit_eur == pytest.approx(expected)
    assert any(c.objective.value == "financial_result" and c.available
               for c in result.record.objective_comparisons)


@pytest.mark.parametrize("blocked", ["unsupported_charge", "unavailable_storage"])
def test_complete_recovery_keeps_canonical_capability_validation(tmp_path, monkeypatch, blocked):
    snapshot, plan, assignment, _ = complete_recovery_fixture(tmp_path, monkeypatch)
    caps = snapshot.capability_snapshot_set
    if blocked == "unsupported_charge":
        capabilities = tuple(replace(
            c, supported_primitives=tuple(p for p in c.supported_primitives
                                          if p is not ExecutionPrimitive.CHARGE_AT_POWER),
        ) for c in caps.capabilities)
        expected = "unsupported_primitive:charge_at_power"
    else:
        capabilities = tuple(replace(c, availability=CapabilityAvailability.UNAVAILABLE)
                             for c in caps.capabilities)
        expected = "daily_reference_capability_unavailable"
    snapshot = replace(snapshot, capability_snapshot_set=replace(caps, capabilities=capabilities))

    def portfolio():
        return market_rule_planning.market_rule_portfolio(
            snapshot=snapshot, plan=plan, assignment=assignment,
            conversion=inputs()["conversion_model"], opportunity_ids=(),
        )

    if blocked == "unavailable_storage":
        with pytest.raises(ValueError, match=expected):
            portfolio()
        return
    market = portfolio()
    assert market.comparable.candidate_set.candidates == ()
    assert expected in market.reasons
    assert market.comparable.candidate_set.exclusions
    assert all(expected in e.reason for e in market.comparable.candidate_set.exclusions)


def test_completed_recovery_survives_household_drain_in_unchanged_reference(
    tmp_path, monkeypatch,
):
    snapshot, plan, assignment, _ = complete_recovery_fixture(
        tmp_path, monkeypatch, household_energy_wh=20,
    )
    observed = []
    original = market_rule_planning.assess_market_route

    def capture(**kwargs):
        result = original(**kwargs)
        if result.status == "admissible":
            finish = result.recovery_ends_at
            stocks = tuple(next(i.storage_energy_at_end_wh for i in projection.intervals
                                if i.ends_at == finish)
                           for projection in (kwargs["baseline"], kwargs["proposed"]))
            observed.append(stocks)
        return result

    monkeypatch.setattr(market_rule_planning, "assess_market_route", capture)
    market = market_rule_planning.market_rule_portfolio(
        snapshot=snapshot, plan=plan, assignment=assignment,
        conversion=inputs()["conversion_model"], opportunity_ids=(),
    )
    assert market.evidence, market.reasons
    assert any(proposed > baseline + 1e-6 for baseline, proposed in observed)
    assert all(e.admission.incremental_net_profit_eur > 0 for e in market.evidence)
