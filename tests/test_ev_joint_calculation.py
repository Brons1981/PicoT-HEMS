"""Joint pricing must change the battery when that reduces the whole bill."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import request, scenario

from picot.v2.ev_deadline_advice import _overlay, _placement_starts, advise
from picot.v2.ev_joint_selection import rebuilt_selection
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_joint_selection_is_canonical_and_has_no_lower_terminal_reserve(tmp_path):
    _, snapshot, retained = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at
    # EV is fixed; later battery acquisition is much cheaper and leaves more
    # end reserve. Extra stock receives no credit in the total-cash comparison.
    snapshot = replace(
        snapshot,
        price_points=tuple(
            replace(
                p,
                value_eur_per_kwh=0.01
                if at + timedelta(hours=22) <= p.starts_at < at + timedelta(hours=26)
                else 0.8,
            )
            for p in snapshot.price_points
        ),
    )
    query = request(
        snapshot,
        available_from=(at + timedelta(hours=14)).isoformat(),
        ready_by=(at + timedelta(hours=14, minutes=30)).isoformat(),
    )
    proofs = {}
    answer = advise(snapshot, query, inputs()["conversion_model"], selections=proofs)
    assert answer["status"] == "ready", answer
    assert answer["battery_route_changed"], answer
    assert answer["savings_eur"] > 0
    assert answer["total_cost_eur"] < answer["baseline_total_cost_eur"]
    assert all(
        c["terminal_storage_energy_wh"] + 1e-6 >= answer["terminal_storage_requirement_wh"]
        for c in answer["candidate_comparisons"]
        if "total_cost_eur" in c
    )
    proof = proofs[answer["selection_id"]]
    assert proof.window is not None
    assert proof.evaluation.record.winning_candidate_id == proof.plan.winning_candidate_id
    assert proof.trigger.request.request_id == "joint-ev:" + answer["selection_id"]
    assert (
        proof.window.projection.intervals[-1].storage_energy_at_end_wh
        > answer["terminal_storage_requirement_wh"] + 1
    )


def test_rebuild_cannot_buy_savings_with_a_lower_end_reserve(tmp_path):
    _, snapshot, retained = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at
    changed = _overlay(snapshot, at, at + timedelta(minutes=30), 2000, retained.valid_until)
    # An impossible reserve admits no cheap route; no salvage value is invented.
    assert (
        rebuilt_selection(
            changed, request(snapshot), retained, inputs()["conversion_model"], 100000
        )
        is None
    )


def test_rebuilt_route_keeps_daily_goal_and_never_controls_devices(tmp_path):
    store, snapshot, retained = scenario(tmp_path, soc=0.9)
    before = store._load_payload()
    baseline, _ = IndependentDailyReferenceAdapter().committed_plan_projection(
        snapshot=snapshot, plan=retained, conversion_model=inputs()["conversion_model"]
    )
    proof = rebuilt_selection(
        snapshot,
        request(snapshot),
        retained,
        inputs()["conversion_model"],
        baseline.intervals[-1].storage_energy_at_end_wh,
    )
    assert proof is not None
    owner = next(
        a
        for a in snapshot.daily_charge_context.assignments
        if a.assignment_id == proof.window.assignment_id
    )
    assert proof.window.reached_at <= owner.ends_at
    assert (
        proof.window.target_storage_energy_wh
        == snapshot.current_storage_states[0].usable_capacity_wh
    )
    assert store._load_payload() == before


def test_final_admission_uses_future_start_after_long_calculation(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at + timedelta(hours=14)
    not_before = at + timedelta(minutes=16)
    proof = {}
    answer = advise(
        snapshot,
        request(
            snapshot, available_from=at.isoformat(), ready_by=(at + timedelta(hours=1)).isoformat()
        ),
        inputs()["conversion_model"],
        selections=proof,
        execution_not_before=lambda: not_before,
    )
    assert answer["status"] == "ready", answer
    assert datetime.fromisoformat(answer["slots"][0]["starts_at"]) >= not_before
    assert answer["execution_not_before"] == not_before.isoformat()
    assert any(
        "ev_start_elapsed_during_comparison" in c.get("rejection_reasons", [])
        for c in answer["candidate_comparisons"]
    )
    assert len(proof) == 1


def test_all_elapsed_starts_return_explicit_block_without_execution_proof(tmp_path):
    _, snapshot, _ = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at + timedelta(hours=14)
    proofs = {}
    answer = advise(
        snapshot,
        request(
            snapshot,
            available_from=at.isoformat(),
            ready_by=(at + timedelta(minutes=30)).isoformat(),
        ),
        inputs()["conversion_model"],
        selections=proofs,
        execution_not_before=lambda: at + timedelta(seconds=1),
    )
    assert answer["status"] == "blocked", answer
    assert answer["reason"] == "no_future_ev_start_after_comparison"
    assert answer["slots"] == []
    assert proofs == {}


def test_more_than_200_published_price_edges_are_not_sampled_away():
    at = datetime(2026, 11, 1, tzinfo=UTC)
    start = at + timedelta(minutes=2)
    duration = timedelta(minutes=7)
    latest = at + timedelta(hours=36) - duration
    edges = tuple(at + timedelta(minutes=15 * n) for n in range(145))
    starts = _placement_starts(start, latest, duration, edges)
    assert len(starts) == 288
    assert starts == sorted(set(starts))
    assert starts[0] == start
    assert starts[-1] == latest
    for edge in edges:
        if start <= edge <= latest:
            assert edge in starts
        if start <= edge - duration <= latest:
            assert edge - duration in starts
