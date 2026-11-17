from dataclasses import replace
from datetime import timedelta

from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import request, scenario

from picot.v2.ev_deadline_runtime import advise


def test_grid_choice_without_battery_context_or_soc(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot, daily_charge_context=None, current_storage_states=())
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["starts_at"] == (
        snapshot.captured_at + timedelta(hours=14)).isoformat()
    assert answer["joint_acceptance_required"] is False
    assert answer["storage_support_allowed"] is False
    assert not answer.get("selection_id")


def test_blocked_battery_context_does_not_block_grid_choice(tmp_path):
    _, snapshot, plan = scenario(tmp_path, soc=0.9)
    # Current battery plan is irrelevant to the EV's admissible horizon.
    context = replace(snapshot.daily_charge_context, status="blocked", reason="repair pending")
    snapshot = replace(snapshot, daily_charge_context=context)
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["battery_route_changed"] is False


def test_elapsed_calculation_never_returns_a_past_start(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    later = snapshot.captured_at + timedelta(hours=15)
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"],
                    execution_not_before=lambda: later)
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["starts_at"] >= later.isoformat()


def test_missing_prices_does_not_fabricate_a_slot(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    answer = advise(replace(snapshot, price_points=()), request(snapshot), None)
    assert answer["status"] == "blocked"
    assert answer["slots"] == []


def test_surplus_pv_counts_after_house_and_battery_without_changing_plan(tmp_path):
    store, snapshot, _ = scenario(tmp_path, soc=0.9)
    solar_start = snapshot.captured_at + timedelta(hours=2)
    solar_end = solar_start + timedelta(hours=1)
    snapshot = replace(snapshot,
        price_points=tuple(replace(p, value_eur_per_kwh=0.30) for p in snapshot.price_points),
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, intervals=tuple(
            replace(p, pv_energy_wh=2000, forecast_lower_energy_wh=2000,
                    forecast_central_energy_wh=2000, forecast_upper_energy_wh=2000)
            if solar_start <= p.starts_at < solar_end else p
            for p in snapshot.pv_energy_timeline.intervals)))
    before = store._load_payload()
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["pv_assessment"] == "surplus_after_house_and_battery", answer
    assert answer["estimated_pv_energy_wh"] == 1000
    assert solar_start.isoformat() <= answer["slots"][0]["starts_at"] < solar_end.isoformat()
    assert answer["estimated_ev_cost_eur"] < 0.30
    assert store._load_payload() == before


def test_negative_prices_and_fractional_end_choose_cheapest_complete_block(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    cheap = snapshot.captured_at + timedelta(hours=8)
    snapshot = replace(snapshot, daily_charge_context=None,
        price_points=tuple(replace(p, value_eur_per_kwh=-0.1
            if cheap <= p.starts_at < cheap + timedelta(hours=1) else 0.4)
            for p in snapshot.price_points))
    answer = advise(snapshot, request(snapshot, remaining_energy_wh=936, fixed_power_w=2300), None)
    assert answer["slots"][0]["starts_at"] == cheap.isoformat()
    assert abs(answer["estimated_ev_cost_eur"] - -0.0936) < 1e-6
    assert answer["candidate_count"] > 20


def test_generated_advice_runs_without_joint_receipt(tmp_path):
    from test_ev_direct_start import profile
    from test_ev_sessions import Rig

    _, snapshot, _ = scenario(tmp_path / "hems", soc=0.9)
    rig = Rig(tmp_path / "ed")
    rig.now = snapshot.captured_at
    profile(rig)
    rig.manager.action({"action": "request_automatic", "required_energy_wh": 936,
                        "ready_by": (rig.now + timedelta(hours=22)).isoformat()})
    demand = rig.manager.view()["charging_request"]
    answer = advise(replace(snapshot, daily_charge_context=None), demand, None)
    assert rig.manager.receive_advice(answer)
    session = rig.manager.view()["sessions"][-1]
    assert session["confirmed"]
    assert not session.get("joint_pending")
    from datetime import datetime
    rig.now = datetime.fromisoformat(session["planned_start"])
    rig.tick(0, "off")
    assert rig.commands == [True]
    assert rig.manager.snapshot()["storage_support_allowed"] is False
    rig.now = datetime.fromisoformat(session["planned_end"])
    rig.tick(2300, "on")
    assert rig.commands[-1] is False


def test_old_automatic_blockade_is_renewed_without_confirming_old_slot(tmp_path):
    from test_ev_direct_start import profile
    from test_ev_sessions import Rig

    rig = Rig(tmp_path / "ed")
    profile(rig)
    rig.manager.action({"action": "request_automatic", "required_energy_wh": 936,
                        "ready_by": (rig.now + timedelta(hours=12)).isoformat()})
    demand = rig.manager.view()["charging_request"]
    start = rig.now + timedelta(hours=1)
    advice = {"contract": "energy-device-charging-advice:v1", "status": "ready",
              "session_id": demand["session_id"], "request_revision": 1,
              "generated_at": rig.now.isoformat(), "selection_id": "old-joint-choice",
              "slots": [{"starts_at": start.isoformat(),
                         "ends_at": (start + timedelta(seconds=936 / 2300 * 3600)).isoformat(),
                         "energy_wh": 936}]}
    assert rig.manager.receive_advice(advice)
    assert rig.manager.receive_advice(advice | {"execution_status": "blocked",
        "reason": "market binding requires its restored shared plan"})
    rig.manager.refresh_automatic_request()
    view = rig.manager.view()
    assert view["charging_request"]["state"] == "requested"
    assert view["charging_request"]["request_revision"] == 2
    assert view["sessions"][-1]["state"] == "cancelled"
    rig.tick(0, "off")
    assert not rig.commands


def test_pv_needed_by_house_is_not_available_to_ev(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    snapshot = replace(snapshot,
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, intervals=tuple(
            replace(p, pv_energy_wh=25, forecast_lower_energy_wh=25,
                    forecast_central_energy_wh=25, forecast_upper_energy_wh=25)
            for p in snapshot.pv_energy_timeline.intervals)))
    answer = advise(snapshot, request(snapshot), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["estimated_pv_energy_wh"] == 0


def test_incomplete_prices_are_explicitly_provisional(tmp_path):
    _, snapshot, _ = scenario(tmp_path, complete=False, soc=0.9)
    answer = advise(snapshot, request(snapshot, ready_by=(
        snapshot.captured_at + timedelta(hours=30)).isoformat()), None)
    assert answer["status"] == "provisional", answer
    assert answer["provisional_reasons"] == ["prices_missing_before_requested_deadline"]


def test_solar_reserved_for_battery_is_not_credited_to_ev(tmp_path):
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    _, snapshot, plan = scenario(tmp_path, soc=0.9)
    charge = next(s for s in plan.segments if s.main_assignment_id
                  and s.starts_at > snapshot.captured_at)
    end = charge.starts_at + timedelta(hours=1)
    snapshot = replace(snapshot,
        pv_energy_timeline=replace(snapshot.pv_energy_timeline, intervals=tuple(
            replace(p, pv_energy_wh=300, forecast_lower_energy_wh=300,
                    forecast_central_energy_wh=300, forecast_upper_energy_wh=300)
            if charge.starts_at <= p.starts_at < end else p
            for p in snapshot.pv_energy_timeline.intervals)))
    projection, _ = IndependentDailyReferenceAdapter().committed_plan_projection(
        snapshot=snapshot, plan=plan, conversion_model=inputs()["conversion_model"])
    assert sum(i.pv_to_storage_input_wh for i in projection.intervals) > 0
    answer = advise(snapshot, request(snapshot, available_from=charge.starts_at.isoformat(),
                    ready_by=end.isoformat()), inputs()["conversion_model"])
    assert answer["status"] == "ready", answer
    assert answer["estimated_pv_energy_wh"] == 0
