"""Regression: cheap EV hours may consume PV promised to the battery."""

from dataclasses import replace
from datetime import timedelta

from test_daily_main_charge_windows import inputs
from test_ev_deadline_advice import request, scenario

from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.daily_charge_assignment import DailyChargeSegment
from picot.v2.ev_deadline_advice import _overlay, advise
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_earlier_ev_consumes_reserved_pv_and_battery_rebuilds_to_meet_goal(tmp_path):
    _, snapshot, old = scenario(tmp_path, soc=0.9)
    at = snapshot.captured_at
    owner = next(a for a in snapshot.daily_charge_context.assignments if a.completed_at is None)
    solar = replace(
        old.segments[3],
        segment_id="solar-main",
        source_path_segment_id="solar-main",
        starts_at=at + timedelta(hours=12),
        ends_at=at + timedelta(hours=16),
        primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        purpose="main-charge:" + owner.assignment_id,
        main_assignment_id=owner.assignment_id,
        charge_source_policy=ChargeSourcePolicy.PV_ONLY,
    )
    grid = replace(old.segments[4], ends_at=at + timedelta(hours=17))
    segments = (
        *old.segments[:3],
        replace(old.segments[3], ends_at=solar.starts_at),
        solar,
        grid,
        replace(old.segments[5], starts_at=grid.ends_at),
    )
    plan = replace(old, segments=tuple(replace(s, order=n + 1) for n, s in enumerate(segments)))
    owner = replace(
        owner,
        main_segments=(
            DailyChargeSegment(solar.segment_id, solar.starts_at, solar.ends_at),
            DailyChargeSegment(grid.segment_id, grid.starts_at, grid.ends_at),
        ),
    )
    snapshot = replace(
        snapshot,
        daily_charge_context=replace(
            snapshot.daily_charge_context,
            assignments=tuple(
                owner if a.assignment_id == owner.assignment_id else a
                for a in snapshot.daily_charge_context.assignments
            ),
            main_plans=tuple(plan for _ in snapshot.daily_charge_context.main_plans),
        ),
        price_points=tuple(
            replace(
                p,
                value_eur_per_kwh=0.01
                if solar.starts_at <= p.starts_at < at + timedelta(hours=15)
                else 0.8,
            )
            for p in snapshot.price_points
        ),
        pv_energy_timeline=replace(
            snapshot.pv_energy_timeline,
            intervals=tuple(
                replace(
                    p,
                    pv_energy_wh=300,
                    forecast_lower_energy_wh=300,
                    forecast_central_energy_wh=300,
                    forecast_upper_energy_wh=300,
                )
                if solar.starts_at <= p.starts_at < solar.ends_at
                else p
                for p in snapshot.pv_energy_timeline.intervals
            ),
        ),
    )
    conversion = inputs()["conversion_model"]
    early = _overlay(snapshot, solar.starts_at, at + timedelta(hours=15), 2000, plan.valid_until)
    adapter = IndependentDailyReferenceAdapter()
    assert adapter.committed_execution_invalidity_reasons(
        snapshot=early, plan=plan, conversion_model=conversion
    )
    # Only four hours of starts are compared; the expensive late alternative
    # retains the original solar charge, while the cheap early EV needs repair.
    proofs = {}
    answer = advise(
        snapshot,
        request(
            snapshot,
            remaining_energy_wh=6000,
            available_from=solar.starts_at.isoformat(),
            ready_by=(at + timedelta(hours=19)).isoformat(),
        ),
        conversion,
        selections=proofs,
    )
    assert answer["status"] == "ready", answer
    assert answer["slots"][0]["starts_at"] < solar.ends_at.isoformat()
    assert answer["battery_route_changed"], answer
    proof = proofs[answer["selection_id"]]
    assert proof.window.reached_at <= owner.ends_at
    assert answer["savings_eur"] > 0
