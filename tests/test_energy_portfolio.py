"""Batch energy-only alternatives on a real retained HEMS route."""

import copy
from dataclasses import replace
from datetime import timedelta

import pytest
from picot.v2.energy_portfolio import assess
from picot.v2.energy_portfolio_runtime import PortfolioAdvisor
from picot.v2.ha_projection_sink import _ha_attributes
from picot_hc.energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, read_assessment
from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import scenario


def request(snapshot, plans):
    return dict(
        contract="hc-energy-proposals:v1",
        request_id="5a62e739-189d-416c-9a94-004ac2fb7e83",
        revision=1,
        basis_snapshot_id=snapshot.snapshot_id,
        generated_at=snapshot.captured_at.isoformat(),
        valid_until=(snapshot.captured_at + timedelta(seconds=180)).isoformat(),
        demand_basis="additional_to_forecast",
        comfort_equivalent=True,
        plans=plans,
    )


def plan(snapshot, name, energy, cost=0, hours=14):
    return dict(
        plan_id=name,
        additional_non_electric_cost_eur=cost,
        slots=[
            dict(
                starts_at=(snapshot.captured_at + timedelta(hours=hours)).isoformat(),
                ends_at=(snapshot.captured_at + timedelta(hours=hours + 1)).isoformat(),
                additional_energy_wh=energy,
            )
        ],
    )


def test_selects_one_plan_in_batch_including_non_electric_costs(tmp_path):
    store, snapshot, _ = scenario(tmp_path, soc=0.9)
    before = store._load_payload()
    value = request(snapshot, [plan(snapshot, "electric", 500), plan(snapshot, "other", 0, 10)])
    answer = assess(snapshot, value, inputs()["conversion_model"])
    assert answer["status"] == "selected", answer
    assert answer["selected_plan_id"] == "electric"
    assert answer["execution_authorized"] is False
    assert len(answer["assessments"]) == 2
    assert store._load_payload() == before


def test_unaffordable_energy_returns_verified_shape_constraint(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = assess(
        snapshot,
        request(snapshot, [plan(snapshot, "excess", 15000, hours=8)]),
        inputs()["conversion_model"],
    )
    assert answer["status"] == "rejected", answer
    constraint = answer["assessments"][0]["constraint"]
    assert 0 <= constraint["verified_profile_scale"] < 1
    assert constraint["requires_hc_comfort_recheck"]
    assert constraint["budgets_additive"] is False


def test_six_plans_are_rejected_before_computation(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = assess(
        snapshot,
        request(snapshot, [plan(snapshot, str(n), 0) for n in range(6)]),
        inputs()["conversion_model"],
    )
    assert answer["status"] == "blocked"
    assert answer["reason"] == "invalid_proposal_count"


@pytest.mark.parametrize(
    "change", ["nan", "negative", "bool", "duplicate", "overlap", "device", "basis", "unconfirmed"]
)
def test_invalid_contracts_are_blocked(tmp_path, change):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "one", 500)])
    selected = value["plans"][0]
    if change == "nan":
        selected["additional_non_electric_cost_eur"] = float("nan")
    if change == "negative":
        selected["slots"][0]["additional_energy_wh"] = -1
    if change == "bool":
        selected["slots"][0]["additional_energy_wh"] = True
    if change == "duplicate":
        value["plans"].append(copy.deepcopy(selected))
    if change == "overlap":
        selected["slots"].append(copy.deepcopy(selected["slots"][0]))
    if change == "device":
        selected["entity_id"] = "climate.example"
    if change == "basis":
        value["basis_snapshot_id"] = "old"
    if change == "unconfirmed":
        value["demand_basis"] = "total_heating_consumption"
    answer = assess(snapshot, value, inputs()["conversion_model"])
    assert answer["status"] == "blocked"
    assert answer["selected_plan_id"] is None


def test_non_electric_alternative_can_win_and_ties_are_stable(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "electric", 500), plan(snapshot, "other", 0, 0.001)])
    answer = assess(snapshot, value, inputs()["conversion_model"])
    assert answer["selected_plan_id"] == "other"
    value["plans"] = [plan(snapshot, "z", 0), plan(snapshot, "a", 0)]
    assert assess(snapshot, value, inputs()["conversion_model"])["selected_plan_id"] == "a"


def test_missing_future_prices_return_required_horizon(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9, complete=False)
    answer = assess(
        snapshot, request(snapshot, [plan(snapshot, "one", 500)]), inputs()["conversion_model"]
    )
    assert answer["status"] == "blocked"
    assert answer["condition"]["kind"] == "wait_for_prices"
    assert answer["condition"]["required_until"] > answer["price_coverage_until"]


def test_terminal_energy_cannot_be_used_as_free_energy(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "late", 500, hours=24)])
    answer = assess(snapshot, value, inputs()["conversion_model"])
    assert answer["status"] == "rejected"
    row = answer["assessments"][0]
    assert "terminal_storage_must_be_preserved" in row["violations"]
    value["plans"][0]["slots"][0]["additional_energy_wh"] *= row["constraint"][
        "verified_profile_scale"
    ]
    assert assess(snapshot, value, inputs()["conversion_model"])["status"] == "selected"


def test_worker_and_hc_match_revision_fingerprint_and_expiry(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "one", 500)])
    sent = []
    worker = PortfolioAdvisor(
        lambda: copy.deepcopy(value),
        sent.append,
        lambda s: inputs()["conversion_model"],
        now=lambda: snapshot.captured_at,
    )
    worker.refresh(snapshot)
    worker.refresh(snapshot)
    assert len(sent) == 1
    states = {
        REQUEST_ENTITY: dict(state="requested", attributes=value),
        RESPONSE_ENTITY: dict(state=sent[0]["status"], attributes=sent[0]),
    }
    assert read_assessment(states, snapshot.captured_at.timestamp())["selected_plan_id"] == "one"
    assert read_assessment(states, snapshot.captured_at.timestamp() + 120)["status"] == "stale"
    value["revision"] = 2
    assert read_assessment(states, snapshot.captured_at.timestamp())["selected_plan_id"] is None


def test_cancelled_request_during_evaluation_is_not_published(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "one", 500)])
    reads = iter([value, None])
    sent = []
    worker = PortfolioAdvisor(
        lambda: next(reads),
        sent.append,
        lambda s: inputs()["conversion_model"],
        now=lambda: snapshot.captured_at,
    )
    worker.refresh(snapshot)
    assert sent == []


def test_previous_published_basis_remains_usable_for_one_cycle(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    current = [None]
    sent = []
    clock = [snapshot.captured_at]
    worker = PortfolioAdvisor(
        lambda: current[0],
        sent.append,
        lambda s: inputs()["conversion_model"],
        now=lambda: clock[0],
    )
    worker.refresh(snapshot)
    current[0] = request(snapshot, [plan(snapshot, "one", 500)])
    clock[0] += timedelta(seconds=60)
    newer = replace(
        snapshot,
        snapshot_id="next",
        daily_charge_context=None,
        pv_energy_timeline=None,
        household_load_forecast=None,
        capability_snapshot_set=None,
    )
    worker.refresh(newer)
    assert sent[0]["status"] == "selected"
    assert sent[0]["basis_snapshot_id"] == snapshot.snapshot_id


def test_five_alternatives_fit_transport_and_do_not_share_one_budget(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, str(n), 500, n) for n in range(5)])
    answer = assess(snapshot, value, inputs()["conversion_model"])
    assert len(answer["assessments"]) == 5
    assert answer["selected_plan_id"] == "0"
    assert _ha_attributes(answer) == answer
    assert len({row["incremental_electricity_cost_eur"] for row in answer["assessments"]}) == 1


def test_hc_rejects_mismatched_selected_id_and_false_execution_permission(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, [plan(snapshot, "one", 0)])
    answer = assess(snapshot, value, inputs()["conversion_model"])
    states = {
        REQUEST_ENTITY: dict(state="requested", attributes=value),
        RESPONSE_ENTITY: dict(state="selected", attributes=answer),
    }
    answer["selected_plan_id"] = "missing"
    assert read_assessment(states, snapshot.captured_at.timestamp())["status"] == "invalid"
    answer["selected_plan_id"] = "one"
    answer["execution_authorized"] = True
    assert read_assessment(states, snapshot.captured_at.timestamp())["selected_plan_id"] is None
