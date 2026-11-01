"""EV advisory uses actual retained-route physics, settlement and Evaluation."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario as market_scenario

from picot.domain.external_load_policy import ExternalLoadPolicy
from picot.v2.ev_deadline_advice import advise


def scenario(tmp_path, **kwargs):
    store, snapshot, plan = market_scenario(tmp_path, **kwargs)
    # The source fixture deliberately needs bridge repair at 400 W. Retain the
    # same charged/export route with feasible 200 W household demand instead.
    snapshot = replace(snapshot, household_load_forecast=replace(
        snapshot.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=50) for i in snapshot.household_load_forecast.intervals)))
    return store, snapshot, plan


def request(snapshot, **changes):
    value = {
        "contract": "energy-device-charging-request:v1",
        "session_id": "04b7f11d-3589-442e-b594-7cb1bf148eae", "request_revision": 1,
        "state": "requested", "available_from": snapshot.captured_at.isoformat(),
        "ready_by": (snapshot.captured_at + timedelta(hours=22)).isoformat(),
        "remaining_energy_wh": 1000, "fixed_power_w": 2000,
        "evidence_source": "user_grid_energy_estimate",
        "evidence_at": snapshot.captured_at.isoformat(),
    }
    return value | changes


def test_real_comparison_selects_low_price_without_mutating_committed_plan(tmp_path):
    store, snapshot, plan = scenario(tmp_path, soc=0.9)
    before = store._load_payload()
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["starts_at"] == (
        snapshot.captured_at + timedelta(hours=14)).isoformat()
    assert answer["scheduled_energy_wh"] == 1000
    assert answer["retained_plan_id"] == plan.plan_id
    assert answer["estimated_incremental_cost_eur"] > 0
    assert store._load_payload() == before


def test_missing_battery_horizon_prices_blocks_incomplete_total_comparison(tmp_path):
    _, snapshot, _ = scenario(tmp_path, complete=False, soc=0.9)
    answer = advise(snapshot, request(snapshot, ready_by=(
        snapshot.captured_at + timedelta(hours=40)).isoformat()), inputs()["conversion_model"])
    assert answer["status"] == "blocked", answer
    assert answer["reason"] == "joint_comparison_battery_horizon_prices_incomplete"


def test_deadline_after_complete_plan_is_explicitly_provisional(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = advise(snapshot, request(snapshot, available_from=(
        snapshot.captured_at + timedelta(hours=35)).isoformat(), ready_by=(
        snapshot.captured_at + timedelta(hours=40)).isoformat()), inputs()["conversion_model"])
    assert answer["status"] == "provisional", answer
    assert "battery_plan_ends_before_requested_deadline" in answer["provisional_reasons"]
    assert "prices_missing_before_requested_deadline" in answer["provisional_reasons"]


@pytest.mark.parametrize("changes,reason", [
    ({"remaining_energy_wh": float("nan")}, "invalid_request_number"),
    ({"fixed_power_w": True}, "invalid_request_number"),
    ({"fixed_power_w": None}, "invalid_request_number"),
    ({"ready_by": "2026-10-25T02:30:00"}, "request_time_requires_offset"),
    ({"state": "cancelled"}, "invalid_request_contract"),
])
def test_invalid_request_fails_closed(tmp_path, changes, reason):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = advise(snapshot, request(snapshot, **changes), inputs()["conversion_model"])
    assert answer["status"] == "blocked"
    assert answer["reason"] == reason
    assert answer["slots"] == []


def test_impossible_deadline_is_distinct_from_missing_price_evidence(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = advise(snapshot, request(snapshot, remaining_energy_wh=80000),
                    inputs()["conversion_model"])
    assert answer["status"] == "infeasible"
    missing = replace(snapshot, price_points=())
    answer = advise(missing, request(missing), inputs()["conversion_model"])
    assert answer["status"] == "blocked"
    assert answer["slots"] == []


def test_identity_and_revision_are_echoed_on_restart(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, request_revision=3, available_from=(
        snapshot.captured_at + timedelta(hours=14)).isoformat(), ready_by=(
        snapshot.captured_at + timedelta(hours=16)).isoformat())
    first = advise(snapshot, value, inputs()["conversion_model"])
    second = advise(snapshot, value, inputs()["conversion_model"])
    assert first == second
    assert first["request_revision"] == 3


def test_active_load_blocks_double_counting(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot, external_load_policy=ExternalLoadPolicy(
        "ev", "1", snapshot.captured_at, 2000, False, "battery"))
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["reason"] == "existing_ev_demand_requires_reconciliation"
    assert answer["slots"] == []


def test_invalid_retained_route_does_not_become_an_ev_candidate(tmp_path):
    _, snapshot, _ = market_scenario(tmp_path, soc=0.9)
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["reason"] == "retained_battery_plan_requires_repair"


def test_offset_equivalent_deadlines_compare_as_instants(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    value = request(snapshot, ready_by="2026-08-23T12:32:00+02:00")
    answer = advise(snapshot, value, inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["ends_at"] == "2026-08-23T10:32:00+00:00"


def test_pv_cashflow_can_win_over_lower_market_price(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot, price_points=tuple(
        # With 2026 saldering the self-consumption advantage is very small:
        # supplier addition including VAT minus export addition = 0.0000013.
        replace(p, value_eur_per_kwh=0.100001 if n < 2 else 0.1)
        for n, p in enumerate(snapshot.price_points)),
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, intervals=tuple(
            replace(p, pv_energy_wh=1000, forecast_lower_energy_wh=1000,
                    forecast_central_energy_wh=1000, forecast_upper_energy_wh=1000)
            if n < 2 else p for n, p in enumerate(snapshot.pv_energy_timeline.intervals))))
    answer = advise(snapshot, request(snapshot, ready_by=(
        snapshot.captured_at + timedelta(hours=2)).isoformat()), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["starts_at"] == (
        snapshot.captured_at + timedelta(seconds=120)).isoformat()


def test_dst_fold_ready_by_has_distinct_elapsed_capacity(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot, captured_at=datetime.fromisoformat("2026-10-25T00:00:00+00:00"),
                       daily_charge_context=None, active_plan_commitments=(),
                       capability_snapshot_set=None, storage_mode_capability_evidence=None)
    late = advise(snapshot, request(snapshot, remaining_energy_wh=1500,
                                   ready_by="2026-10-25T02:30:00+01:00"),
                  inputs()["conversion_model"])
    early = advise(snapshot, request(snapshot, remaining_energy_wh=1500,
                                    ready_by="2026-10-25T02:30:00+02:00"),
                   inputs()["conversion_model"])
    assert late["reason"] == "retained_battery_plan_unavailable"
    assert early["status"] == "infeasible"


def test_partial_quarter_energy_is_not_rounded_up(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    start = snapshot.captured_at + timedelta(seconds=120)
    end = start + timedelta(hours=1234 / 2000)
    answer = advise(snapshot, request(snapshot, remaining_energy_wh=1234,
                    ready_by=end.isoformat()), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["slots"] == [{"starts_at": start.isoformat(),
                               "ends_at": end.isoformat(), "energy_wh": 1234}]
