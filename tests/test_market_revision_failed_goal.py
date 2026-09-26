"""A failed original daily goal and missing market prices cannot block safe repair."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from test_daily_main_charge_windows import inputs
from test_market_revision_comparison import scenario

from picot.domain.evaluation import CandidateValidity
from picot.planner.market_revision_candidates import market_revision_windows
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
from picot.v2.live_runtime import _restore_daily_charge_context
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.plan_commitment_store import _serialize_daily, _serialize_execution_plan


def failed_main_scenario(tmp_path, *, complete=True):
    store, snapshot, plan = scenario(tmp_path, complete=complete)
    context = snapshot.daily_charge_context
    owner = next(a for a in context.assignments if a.completed_at is None)
    stop = owner.main_segments[0].starts_at + timedelta(hours=1)
    modified_plan = replace(plan, segments=tuple(
        replace(segment, ends_at=stop) if segment.main_assignment_id == owner.assignment_id
        else replace(segment, starts_at=stop)
        if segment.starts_at == owner.main_segments[0].ends_at else segment
        for segment in plan.segments
    ))
    owner = replace(owner, main_segments=tuple(
        replace(segment, ends_at=stop) for segment in owner.main_segments
    ))
    owners = tuple(owner if a.assignment_id == owner.assignment_id else a
                   for a in context.assignments)
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in owners},
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(modified_plan)
                               for a in owners},
        execution_plans={modified_plan.plan_id: _serialize_execution_plan(modified_plan)},
    )
    store._write(payload)
    # The one-hour original main route cannot fill storage. Later reduced demand
    # makes every successful repair finish above that invalid incumbent's stock.
    snapshot = replace(snapshot, household_load_forecast=replace(
        snapshot.household_load_forecast, intervals=tuple(
            replace(interval, expected_energy_wh=0) if interval.starts_at >= stop else interval
            for interval in snapshot.household_load_forecast.intervals
        ),
    ))
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    assert snapshot.daily_charge_context.status == "ready"
    return store, snapshot, owner


def test_failed_main_goal_has_valid_repair_without_reopening_completed_day(tmp_path):
    store, snapshot, owner = failed_main_scenario(tmp_path)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    shortfalls = adapter.main_route_shortfalls(snapshot=snapshot, conversion_model=conversion)
    assert any(trigger.assignment_id == owner.assignment_id for trigger in shortfalls)
    completed = next(a for a in store.load_daily_assignments() if a.completed_at is not None)
    run = CanonicalPipeline(
        commitment_store=store, market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert run.evaluation.status == "winner_selected", run.evaluation.reason
    winner = next(outcome for outcome in run.outcomes.canonical_outcomes
                  if outcome.candidate_id == run.evaluation.winning_candidate_id)
    assert winner.validity is CandidateValidity.VALID
    assert next(a for a in store.load_daily_assignments()
                if a.assignment_id == completed.assignment_id) == completed
    active = store.load_active_daily_main_plan(owner.execution_scope_id)
    assert active.winning_candidate_id == run.evaluation.winning_candidate_id
    restored = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    assert not any(trigger.assignment_id == owner.assignment_id for trigger in
                   adapter.main_route_shortfalls(snapshot=restored, conversion_model=conversion))


def test_incomplete_tomorrow_coverage_cannot_admit_changed_export(tmp_path):
    store, snapshot, plan = scenario(tmp_path, complete=False)
    run = CanonicalPipeline(
        commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert run.evaluation.status in {"plan_retained", "winner_selected"}, run.evaluation.reason
    evidence = run.outcomes.market_revision_evidence
    winner_evidence = next(e for e in evidence
                           if e.candidate_id == run.evaluation.winning_candidate_id)
    assert winner_evidence.variant == "retained"
    changed = tuple(e for e in evidence if e.variant in {"shortened", "removed"})
    assert changed
    assert all("market_revision_today_tomorrow_coverage_incomplete" in e.invalidity_reasons
               for e in changed)
    outcomes = {outcome.candidate_id: outcome for outcome in run.outcomes.canonical_outcomes}
    assert all(outcomes[e.candidate_id].validity is CandidateValidity.INVALID for e in changed)
    active = store.load_active_daily_main_plan("battery")
    assert active is not None
    if run.evaluation.status == "plan_retained":
        assert active == plan
    else:
        assert active.winning_candidate_id == run.evaluation.winning_candidate_id


def test_prices_ending_before_future_main_do_not_erase_a_valid_incumbent(tmp_path):
    store, snapshot, plan = scenario(tmp_path)
    snapshot = replace(snapshot, price_points=snapshot.price_points[:48])
    conversion = inputs()["conversion_model"]
    assert not IndependentDailyReferenceAdapter().main_route_shortfalls(
        snapshot=snapshot, conversion_model=conversion,
    )
    before = store._path.read_bytes()
    run = CanonicalPipeline(
        commitment_store=store, market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert run.evaluation.status == "plan_retained", run.evaluation.reason
    assert "prices_do_not_cover" in run.evaluation.reason
    assert run.execution_plan_set.plan_ids == (plan.plan_id,)
    assert store.load_active_daily_main_plan("battery") == plan
    assert store._path.read_bytes() == before


def test_short_old_plan_does_not_truncate_available_tomorrow_comparison(tmp_path):
    _, snapshot, plan = scenario(tmp_path)
    old_end = plan.valid_until - timedelta(hours=2)
    shorter = replace(plan, valid_until=old_end, segments=tuple(
        replace(segment, ends_at=old_end) if segment.ends_at == plan.valid_until else segment
        for segment in plan.segments
    ))
    snapshot = replace(snapshot, daily_charge_context=replace(
        snapshot.daily_charge_context,
        main_plans=tuple(shorter if item.plan_id == plan.plan_id else item
                         for item in snapshot.daily_charge_context.main_plans),
    ))
    conversion = inputs()["conversion_model"]
    trigger = IndependentDailyReferenceAdapter().bridge_assessment(
        snapshot=snapshot, conversion_model=conversion,
    ).trigger
    assert trigger is not None
    windows = market_revision_windows(snapshot=snapshot, trigger=trigger,
                                      conversion_model=conversion)
    assert windows.market_revision.horizon_complete
    assert windows.market_revision.horizon_end == snapshot.horizon_end
    assert windows.market_revision.horizon_end > old_end
    assert windows.windows
    assert all(window.schedule.horizon_end == snapshot.horizon_end for window in windows.windows)


def full_37_hour_snapshot(snapshot):
    # Start at the observed end of today's original charge, one hour earlier.
    # Tomorrow's local midnight is now 37 hours away, within a two-day plan.
    start = snapshot.captured_at - timedelta(hours=1)
    quarter = timedelta(minutes=15)

    def preceding(interval, prefix):
        return tuple(replace(
            interval, interval_id=f"{prefix}:early:{index}",
            starts_at=start + index * quarter, ends_at=start + (index + 1) * quarter,
        ) for index in range(4))

    household = snapshot.household_load_forecast
    pv = snapshot.pv_energy_timeline
    return replace(
        snapshot, captured_at=start,
        daily_charge_context=replace(snapshot.daily_charge_context, restored_at=start),
        capability_snapshot_set=replace(
            snapshot.capability_snapshot_set, captured_at=start,
            capabilities=tuple(replace(capability, fresh_at=start)
                               for capability in snapshot.capability_snapshot_set.capabilities),
        ),
        current_storage_states=tuple(replace(state, measured_at=start)
                                     for state in snapshot.current_storage_states),
        price_points=tuple(replace(
            snapshot.price_points[0], point_id=f"p:early:{index}",
            starts_at=start + index * quarter, ends_at=start + (index + 1) * quarter,
        ) for index in range(4)) + snapshot.price_points,
        household_load_forecast=replace(household, intervals=(
            preceding(household.intervals[0], "h") + household.intervals)),
        pv_energy_timeline=replace(pv, intervals=(
            preceding(pv.intervals[0], "pv") + pv.intervals)),
    )


def test_committed_projection_and_goal_monitor_accept_full_37_hour_plan(tmp_path):
    _, snapshot, plan = scenario(tmp_path)
    snapshot = full_37_hour_snapshot(snapshot)
    assert plan.valid_until - snapshot.captured_at == timedelta(hours=37)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    projection, schedule = adapter.committed_plan_projection(
        snapshot=snapshot, plan=plan, conversion_model=conversion,
    )
    assert schedule.horizon_start == snapshot.captured_at
    assert schedule.horizon_end == snapshot.horizon_end
    assert projection.intervals[-1].ends_at == snapshot.horizon_end
    assert not adapter.main_route_shortfalls(snapshot=snapshot, conversion_model=conversion)


@pytest.mark.parametrize("repair", ["bridge", "main"])
def test_repair_after_export_removal_keeps_committed_37_hour_horizon(tmp_path, repair):
    from picot.domain.daily_reference_intent import DailyStorageIntent
    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.planner.market_revision_candidates import market_revision_available

    if repair == "main":
        _, snapshot, _ = failed_main_scenario(tmp_path)
        plan = next(p for p in snapshot.daily_charge_context.main_plans
                    if p.plan_id in snapshot.daily_charge_context.active_main_plan_ids)
    else:
        _, snapshot, plan = scenario(tmp_path)
    snapshot = full_37_hour_snapshot(snapshot)
    removed = replace(plan, segments=tuple(
        replace(segment, primitive=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
                requested_power_w=None, purpose="retained-route")
        if segment.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER else segment
        for segment in plan.segments
    ))
    snapshot = replace(snapshot, daily_charge_context=replace(
        snapshot.daily_charge_context, market_plan_bindings=(),
        main_plans=tuple(removed if item.plan_id == plan.plan_id else item
                         for item in snapshot.daily_charge_context.main_plans),
    ))
    assert not market_revision_available(snapshot)
    assert plan.valid_until - snapshot.captured_at == timedelta(hours=37)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    if repair == "bridge":
        trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
        assert trigger is not None
        windows = adapter.bridge_windows(snapshot=snapshot, trigger=trigger,
                                         conversion_model=conversion)
    else:
        trigger, = adapter.main_route_shortfalls(snapshot=snapshot, conversion_model=conversion)
        owner = next(a for a in snapshot.daily_charge_context.assignments
                     if a.assignment_id == trigger.assignment_id)
        windows = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
                                              optimisation_trigger=trigger,
                                              conversion_model=conversion)
    assert windows.windows
    assert windows.market_revision is None
    assert all(window.schedule.horizon_end == plan.valid_until for window in windows.windows)
    assert all(interval.intent is not DailyStorageIntent.STORAGE_EXPORT
               for window in windows.windows for interval in window.schedule.intervals)


@pytest.mark.parametrize("missing", ["household", "pv"])
def test_missing_forecast_only_beyond_valid_active_plan_cannot_force_fallback(tmp_path, missing):
    store, snapshot, plan = scenario(tmp_path)
    active_end = plan.valid_until - timedelta(hours=2)
    shorter = replace(plan, valid_until=active_end, segments=tuple(
        replace(segment, ends_at=active_end) if segment.ends_at == plan.valid_until else segment
        for segment in plan.segments
    ))
    owners = store.load_daily_assignments()
    payload = store._load_payload()
    payload.update(
        daily_execution_plans={a.assignment_id: _serialize_execution_plan(shorter) for a in owners},
        execution_plans={shorter.plan_id: _serialize_execution_plan(shorter)},
    )
    store._write(payload)
    if missing == "household":
        snapshot = replace(snapshot, household_load_forecast=replace(
            snapshot.household_load_forecast, intervals=tuple(
                i for i in snapshot.household_load_forecast.intervals if i.ends_at <= active_end
            ),
        ))
    else:
        snapshot = replace(snapshot, pv_energy_timeline=replace(
            snapshot.pv_energy_timeline, intervals=tuple(
                i for i in snapshot.pv_energy_timeline.intervals if i.ends_at <= active_end
            ),
        ))
    snapshot = _restore_daily_charge_context(snapshot, store,
                                             local_timezone=ZoneInfo("Europe/Amsterdam"))
    conversion = inputs()["conversion_model"]
    assert not IndependentDailyReferenceAdapter().main_route_shortfalls(
        snapshot=snapshot, conversion_model=conversion,
    )
    previous_binding, = store.load_market_plan_bindings()
    run = CanonicalPipeline(
        commitment_store=store, market_daily_planner_runtime=MarketDailyPlannerRuntime(conversion),
    ).run(planning_input=snapshot, control_change_allowed=False)
    assert run.evaluation.status in {"winner_selected", "plan_retained"}, run.evaluation.reason
    active = store.load_active_daily_main_plan("battery")
    assert active is not None
    binding, = store.load_market_plan_bindings()
    assert binding.assignment_id == previous_binding.assignment_id
    assert binding.expected_export_wh == previous_binding.expected_export_wh
    assert binding.cancelled_export_wh == 0
    assert binding.elapsed_planned_export_wh == 0
    assert sum(binding.segment_export_wh) == sum(previous_binding.segment_export_wh)
    evidence = run.outcomes.market_revision_evidence
    assert evidence
    assert all(e.comparable_result_eur is None for e in evidence)
    changed = tuple(e for e in evidence if e.variant in {"shortened", "removed"})
    assert changed
    assert all("market_revision_today_tomorrow_coverage_incomplete" in e.invalidity_reasons
               for e in changed)
    completed = next(a for a in owners if a.completed_at is not None)
    assert next(a for a in store.load_daily_assignments()
                if a.completed_at is not None) == completed


def test_market_revision_candidate_exhaustion_preserves_active_charge_continuity(
    tmp_path, monkeypatch,
):
    from test_daily_main_active_pipeline import setup
    from test_daily_main_route_optimisation import fresh
    from test_market_plan_binding import proposal

    from picot.domain.daily_reference_charge_window import DailyMainChargeWindowSet
    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.v2.household_load_guard import HouseholdLoadGuardAssessment

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover(fresh(recover(), pv_factor=0, soc=0.7)))
    original = store.load_active_daily_main_plan("battery")
    proposed = proposal(store, original)
    store.bind_market_plan(**proposed)
    active = store.load_active_daily_main_plan("battery")
    grid = next(s for s in active.segments if s.primitive is ExecutionPrimitive.CHARGE_AT_POWER)
    market = next(s for s in active.segments
                  if s.primitive is ExecutionPrimitive.DISCHARGE_AT_POWER)
    assert market.starts_at >= grid.ends_at
    at = grid.starts_at
    source = first.planning_input
    source = replace(
        source, captured_at=at, daily_charge_context=None,
        current_storage_states=tuple(replace(s, current_soc=0.1, measured_at=at)
                                     for s in source.current_storage_states),
        capability_snapshot_set=replace(
            source.capability_snapshot_set, captured_at=at,
            capabilities=tuple(replace(c, supported_primitives=tuple(ExecutionPrimitive))
                               for c in source.capability_snapshot_set.capabilities),
        ),
        household_load_guard=HouseholdLoadGuardAssessment(True, "reliable", 2000, at, at),
    )

    def exhausted(self, *, snapshot, assignment, **kwargs):
        return DailyMainChargeWindowSet(
            assignment.assignment_id, snapshot.snapshot_id, (), "unreachable",
            "ongoing_load_requires_committed_grid_continuity", 1,
        )

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "main_charge_windows", exhausted)
    before = store._path.read_bytes()
    run = pipeline.run(planning_input=recover(source))
    assert run.evaluation.daily_main_input_shortfalls
    assert run.outcomes.market_revision_evidence
    assert run.evaluation.status == "plan_retained", run.evaluation.reason
    assert run.evaluation.reason == "ongoing_load_requires_committed_grid_continuity"
    assert run.primitive_boundary.planned_primitive is ExecutionPrimitive.CHARGE_AT_POWER
    assert store.load_active_daily_main_plan("battery") == active
    assert store._path.read_bytes() == before


def test_unbound_tomorrow_cannot_provide_free_goal_in_market_comparison(tmp_path):
    from test_daily_main_route_optimisation import fresh

    from picot.v2.daily_charge_assignment import DailyChargeAssignment

    store, snapshot, plan = scenario(tmp_path, export_prices=(-0.5, -0.5))
    today, tomorrow = store.load_daily_assignments()
    # Current plan needs a real repair; tomorrow has been published but its
    # independent 100% goal has not yet received an admitted charging plan.
    today = replace(today, completed_at=None, completion_evidence_id=None,
                    completion_segment_id=None)
    tomorrow = DailyChargeAssignment(
        tomorrow.execution_scope_id, tomorrow.delivery_date, tomorrow.timezone, tomorrow.created_at,
    )
    current_plan = replace(plan, valid_until=today.ends_at, segments=tuple(
        replace(segment, ends_at=min(segment.ends_at, today.ends_at))
        for segment in plan.segments if segment.starts_at < today.ends_at
    ))
    payload = store._load_payload()
    payload.update(
        daily_assignments={a.assignment_id: _serialize_daily(a) for a in (today, tomorrow)},
        daily_execution_plans={today.assignment_id: _serialize_execution_plan(current_plan)},
        execution_plans={current_plan.plan_id: _serialize_execution_plan(current_plan)},
    )
    store._write(payload)
    snapshot = replace(snapshot, price_points=tuple(
        replace(price, value_eur_per_kwh=0.01)
        if price.starts_at < snapshot.captured_at + timedelta(hours=4) else price
        for price in snapshot.price_points
    ))
    zone = ZoneInfo("Europe/Amsterdam")
    snapshot = _restore_daily_charge_context(snapshot, store, local_timezone=zone)
    assert snapshot.daily_charge_context.status == "ready"
    before, = store.load_market_plan_bindings()
    pipeline = CanonicalPipeline(
        commitment_store=store,
        market_daily_planner_runtime=MarketDailyPlannerRuntime(inputs()["conversion_model"]),
    )
    first = pipeline.run(planning_input=snapshot, control_change_allowed=False)
    assert first.evaluation.status == "winner_selected", first.evaluation.reason
    first_owners = {a.assignment_id: a for a in store.load_daily_assignments()}
    assert first_owners[today.assignment_id].route_plan_id != current_plan.plan_id
    assert first_owners[tomorrow.assignment_id].route_plan_id is None
    assert all(a.completed_at is None for a in first_owners.values())
    after, = store.load_market_plan_bindings()
    assert after.expected_export_wh == before.expected_export_wh
    assert after.cancelled_export_wh == 0
    assert sum(after.segment_export_wh) == sum(before.segment_export_wh)
    evidence = first.outcomes.market_revision_evidence
    assert evidence
    reason = f"market_revision_daily_goal_not_planned:{tomorrow.assignment_id}"
    assert all(reason in e.invalidity_reasons for e in evidence)
    assert all(e.comparable_result_eur is None and e.delta_from_incumbent_eur is None
               for e in evidence)
    changed_ids = {e.candidate_id for e in evidence if e.variant in {"removed", "shortened"}}
    assert changed_ids
    assert all(o.validity is CandidateValidity.INVALID and reason in o.invalidity_reasons
               for o in first.outcomes.canonical_outcomes if o.candidate_id in changed_ids)

    next_snapshot = _restore_daily_charge_context(
        fresh(snapshot, tag="unbound-tomorrow"), store, local_timezone=zone,
    )
    second = pipeline.run(planning_input=next_snapshot, control_change_allowed=False)
    assert second.evaluation.status == "winner_selected", second.evaluation.reason
    second_owners = {a.assignment_id: a for a in store.load_daily_assignments()}
    assert second_owners[today.assignment_id] == first_owners[today.assignment_id]
    assert second_owners[tomorrow.assignment_id].route_plan_id is not None
    assert second_owners[tomorrow.assignment_id].main_segments
    assert all(a.completed_at is None for a in second_owners.values())
    path = next(p for p in second.candidate_set.energy_paths
                if p.path_id == second.evaluation.winning_energy_path_id)
    assert max(state.battery_soc for state in path.projected_states
               if state.at >= tomorrow.starts_at) == 1.0
