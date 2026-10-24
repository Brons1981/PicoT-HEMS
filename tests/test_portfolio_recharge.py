import copy
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_selection import snapshot_for_main
from test_daily_main_charge_windows import inputs
from test_load_replacement import basis_for, proposal

from picot.v2.accepted_loads import AcceptedLoads
from picot.v2.energy_portfolio import assess
from picot.v2.energy_portfolio_runtime import PortfolioAdvisor
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore
from picot.v2.planning_input import PlanningInputBundle


def case(tmp_path, late=False):
    store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    model = inputs()["conversion_model"]
    pipeline = CanonicalPipeline(
        market_daily_planner_runtime=MarketDailyPlannerRuntime(model),
        commitment_store=store,
    )
    snapshot = snapshot_for_main()
    snapshot = replace(
        snapshot,
        household_load_forecast=replace(
            snapshot.household_load_forecast,
            intervals=tuple(
                replace(i, expected_energy_wh=50)
                for i in snapshot.household_load_forecast.intervals
            ),
        ),
    )

    def recover(s):
        return _restore_daily_charge_context(s, store, local_timezone=ZoneInfo("UTC"))

    run = pipeline.run(planning_input=recover(snapshot))
    retained = run.execution_plan_set.plans[0]
    snapshot = recover(snapshot)
    basis = basis_for(snapshot)
    value = proposal(snapshot, basis, 3000)
    segment = next(s for s in retained.segments if s.primitive.value == "charge_at_power")
    value["plans"][0]["slots"][0].update(
        starts_at=snapshot.captured_at.isoformat(),
        ends_at=segment.starts_at.isoformat(),
    )
    if late:
        value["plans"][0]["slots"][0].update(
            starts_at=(snapshot.captured_at + timedelta(hours=8)).isoformat(),
            ends_at=(snapshot.captured_at + timedelta(hours=9)).isoformat(),
            energy_wh=1000,
        )
    return store, snapshot, basis, value, model, pipeline, recover


def test_extra_charging_is_costed_without_committing_or_permitting(tmp_path):
    store, snapshot, basis, value, model, _, _ = case(tmp_path)
    before = store._load_payload()
    answer = assess(snapshot, value, model, basis)
    assert answer["status"] == "selected", answer
    assert answer["requires_route_commitment"] is True
    assert answer["execution_authorized"] is False
    row = answer["assessments"][0]
    assert row["additional_grid_charge_wh"] > 0
    assert row["incremental_electricity_cost_eur"] > 0
    assert row["terminal_storage_preserved"]
    assert store._load_payload() == before


def acknowledge(value, answer):
    return dict(
        contract="hc-energy-selection:v1",
        execution_authorized=False,
        **{
            k: value[k]
            for k in (
                "request_id",
                "revision",
                "basis_snapshot_id",
                "replacement_basis_id",
                "generated_at",
                "valid_until",
            )
        },
        request_fingerprint=answer["request_fingerprint"],
        selected_plan_id=answer["selected_plan_id"],
    )


@pytest.mark.parametrize("late", [False, True])
def test_reserve_replan_then_fresh_permission_and_restart_guards(tmp_path, late):
    store, snapshot, basis, value, model, pipeline, recover = case(tmp_path, late=late)
    journal = AcceptedLoads(tmp_path / "accepted.sqlite")
    messages, permits = [], []
    confirmation = [None]
    worker = PortfolioAdvisor(
        lambda: value,
        messages.append,
        lambda s: model,
        now=lambda: snapshot.captured_at,
        read_selection=lambda: confirmation[0],
        accepted_loads=journal,
        publish_permit=permits.append,
    )
    worker.refresh(snapshot, basis)
    confirmation[0] = acknowledge(value, worker.last_answer)
    confirmation[0]["valid_until"] = worker.last_answer["valid_until"]
    worker.poll_selection()
    assert permits[-1]["state"] == "withdrawn"
    selected = confirmation[0]
    receipt = dict(
        contract="hc-energy-reservation:v1",
        status="reserved",
        **{k: selected[k] for k in ("request_id", "request_fingerprint", "selected_plan_id")},
        reported_at=snapshot.captured_at.isoformat(),
        valid_until=(snapshot.captured_at + timedelta(seconds=120)).isoformat(),
    )
    assert journal.reserve(receipt, snapshot.captured_at)
    restarted = AcceptedLoads(journal.path)
    floor = restarted.terminal_requirement(basis.source_id, snapshot.captured_at)
    assert floor == worker.last_answer["terminal_requirement"]
    execution = dict(
        receipt,
        contract="hc-energy-execution:v1",
        status="running",
        executed_at=receipt["reported_at"],
    )
    execution.pop("valid_until")
    assert not restarted.observe(execution, snapshot.captured_at)
    bundle = PlanningInputBundle(
        snapshot, (), (), snapshot.captured_at, snapshot.captured_at, load_replacement_basis=basis
    )
    applied = restarted.apply(bundle)
    assert applied.snapshot.household_load_forecast != snapshot.household_load_forecast
    old = store.load_active_daily_main_plan("battery")
    old_owners = store.load_daily_assignments()
    run = pipeline.run(planning_input=applied.snapshot)
    assert run.execution_plan_set.plans
    assert store.load_active_daily_main_plan("battery").plan_id != old.plan_id
    if late:
        assert store.load_daily_assignments() == old_owners
        assert store.load_reserve_plan_ids()
    current = recover(applied.snapshot)
    worker.refresh(current, applied.load_replacement_basis)
    assert permits[-1]["state"] == "withdrawn"  # cached conditional quote is never permission
    value["revision"] += 1
    value["replacement_basis_id"] = applied.load_replacement_basis.basis_id
    worker.refresh(current, applied.load_replacement_basis)
    assert worker.last_answer["status"] == "selected", worker.last_answer
    assert not worker.last_answer.get("requires_route_commitment")
    assert worker.last_answer["terminal_requirement"] == floor
    confirmation[0] = acknowledge(value, worker.last_answer)
    confirmation[0]["valid_until"] = worker.last_answer["valid_until"]
    worker.poll_selection()
    assert permits[-1]["state"] == "permitted"
    stricter = dict(floor, energy_wh=100000)
    refused = assess(current, value, model, applied.load_replacement_basis, stricter)
    assert refused["status"] == "rejected"
    assert "reserved_terminal_storage_must_be_preserved" in refused["assessments"][0]["violations"]


def test_generic_reserve_enters_planner_signature_and_rejects_unproven_candidates():
    from test_daily_main_charge_selection import evaluate, portfolio_fixture

    from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
    from picot.v2.live_runtime import _planning_input_signature

    snapshot, _, windows, tariffs, _ = portfolio_fixture()
    bundle = PlanningInputBundle(snapshot, (), (), snapshot.captured_at, snapshot.captured_at)
    changed = replace(
        snapshot,
        storage_reserve_checkpoints=(("battery", windows.windows[0].schedule.horizon_end, 100000),),
    )
    assert _planning_input_signature(bundle) != _planning_input_signature(
        replace(bundle, snapshot=changed)
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=changed,
        windows=windows,
        tariffs=tariffs,
        opportunity_ids=(),
    )
    result = evaluate(changed, portfolio)
    assert result.record.winning_candidate_id is None
    assert all(
        "promised_storage_reserve_not_preserved" in o.invalidity_reasons
        for o in portfolio.outcome_set.outcomes
    )


def test_batch_compares_recharge_with_non_electric_cost_and_isolates_failure(tmp_path, monkeypatch):
    _, snapshot, basis, value, model, _, _ = case(tmp_path)
    other = copy.deepcopy(value["plans"][0])
    other.update(plan_id="other", non_electric_cost_eur=10)
    other["slots"][0]["energy_wh"] = 0
    value["plans"].append(other)
    answer = assess(snapshot, value, model, basis)
    assert answer["selected_plan_id"] == "hold", answer
    assert answer["requires_route_commitment"]
    other["non_electric_cost_eur"] = 0
    answer = assess(snapshot, value, model, basis)
    assert answer["selected_plan_id"] == "other", answer
    assert not answer.get("requires_route_commitment")

    def unsupported(*args):
        raise ValueError("unsupported_repair")

    monkeypatch.setattr("picot.v2.energy_portfolio.discover_recharge", unsupported)
    answer = assess(snapshot, value, model, basis)
    assert answer["selected_plan_id"] == "other", answer
    assert answer["assessments"][0]["status"] == "rejected"
