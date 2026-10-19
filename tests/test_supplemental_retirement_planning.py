"""Future supplemental retirement is explicit, physically proved, and side-effect free."""
from dataclasses import replace

from test_daily_main_charge_windows import inputs
from test_supplemental_charge_commitment import charged

from picot.domain.daily_reference_intent import DailyStorageIntent
from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter


def test_obsolete_goal_has_no_charge_alternative_without_mutating_store(tmp_path, monkeypatch):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    source = replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states))
    snapshot = recover(source)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()['conversion_model']
    original = store.load_supplemental_assignments()[0]
    snapshot = replace(snapshot, daily_charge_context=replace(
        snapshot.daily_charge_context,
        supplemental_assignments=(replace(original, target_soc=0.99),)))
    assessment = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion)
    assert assessment.status == 'supplemental_goal_review'
    assert not any(i.deficit_wh > 1e-6 for i in assessment.deficits)
    trigger = assessment.trigger
    assert trigger is not None
    before = store._path.read_bytes()
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion)
    retired = [w for w in windows.windows if original.assignment_id in w.supplemental_retirements]
    assert retired
    assert all(original.assignment_id not in {g.assignment_id for g in w.supplemental_assignments}
               for w in retired)
    for window in retired:
        assert all(i.intent is not DailyStorageIntent.GRID_REQUIREMENT
                   for i in window.schedule.intervals
                   if original.starts_at <= i.starts_at and i.ends_at <= original.ends_at)
    assert store._path.read_bytes() == before
    assert snapshot.daily_charge_context.supplemental_assignments[0].target_soc == 0.99
    assert store.load_supplemental_assignments() == (original,)


def test_necessary_bridge_cannot_be_retired(tmp_path, monkeypatch):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, household_load_forecast=replace(
        source.household_load_forecast, intervals=tuple(
            replace(i, expected_energy_wh=i.expected_energy_wh * 1.1)
            for i in source.household_load_forecast.intervals))))
    adapter = IndependentDailyReferenceAdapter()
    assessment = adapter.bridge_assessment(
        snapshot=snapshot, conversion_model=inputs()['conversion_model'])
    assert assessment.trigger is not None
    windows = adapter.bridge_windows(snapshot=snapshot, trigger=assessment.trigger,
                                     conversion_model=inputs()['conversion_model'])
    assert windows.windows
    assert all(not w.supplemental_retirements for w in windows.windows)


def test_running_or_unowned_supplement_is_never_retirable(tmp_path, monkeypatch):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(source)
    goal = store.load_supplemental_assignments()[0]
    adapter = IndependentDailyReferenceAdapter()
    assert goal in adapter._retirable_supplementals(snapshot, goal.next_assignment_id)
    running = replace(snapshot, captured_at=goal.starts_at,
                      capability_snapshot_set=None, storage_mode_capability_evidence=None,
                      active_plan_commitments=(), daily_charge_context=replace(
                          snapshot.daily_charge_context, restored_at=goal.starts_at))
    assert not adapter._retirable_supplementals(running, goal.next_assignment_id)
    unbound = replace(goal, segment_ids=(), plan_id='')
    context = replace(snapshot.daily_charge_context, supplemental_assignments=(unbound,))
    assert not adapter._retirable_supplementals(replace(snapshot, daily_charge_context=context),
                                               goal.next_assignment_id)


def test_main_review_compares_retiring_and_retained_supplements(tmp_path, monkeypatch):
    from picot.v2.material_replanning import daily_grid_review_comparison

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states)))
    goal = store.load_supplemental_assignments()[0]
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == goal.next_assignment_id)
    comparison_state = next(s for s in snapshot.daily_charge_context.pv_comparison_states
                            if s.assignment_id == owner.assignment_id)
    adapter = IndependentDailyReferenceAdapter()
    comparison = daily_grid_review_comparison(snapshot, comparison_state)
    comparison = replace(comparison, status='complete', actual_wh=100, central_wh=100)
    conversion = inputs()['conversion_model']
    trigger = adapter.pv_surplus_trigger(snapshot=snapshot, assignment=owner,
                                         comparison=comparison, conversion_model=conversion)
    assert trigger is not None
    windows = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
                                          optimisation_trigger=trigger, conversion_model=conversion)
    retired = [w for w in windows.windows if w.supplemental_retirements]
    assert retired
    assert any(not w.supplemental_retirements for w in windows.windows)
    assert all(goal.assignment_id in w.supplemental_retirements for w in retired)

def test_pipeline_persists_selected_retirement_and_restart_does_not_recreate(tmp_path, monkeypatch):
    from picot.v2.material_replanning import daily_grid_review_comparison
    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, pipeline, recover, source, _ = charged(tmp_path, monkeypatch)
    source = replace(source, price_points=tuple(
        replace(p, value_eur_per_kwh=0.60 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
        for p in source.price_points), current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states))
    snapshot = recover(source)
    goal = store.load_supplemental_assignments()[0]
    state = next(s for s in snapshot.daily_charge_context.pv_comparison_states
                 if s.assignment_id == goal.next_assignment_id)
    comparison = replace(daily_grid_review_comparison(snapshot, state),
                         status='complete', actual_wh=100, central_wh=100)
    # Inject a completed comparison at its existing owner seam; physical
    # simulation, candidates, economics, builder and persistence remain real.
    monkeypatch.setattr('picot.v2.mep_canonical_pipeline.daily_grid_review_comparison',
                        lambda *_args: comparison)
    result = pipeline.run(planning_input=snapshot)
    assert result.evaluation.status == 'winner_selected', result.evaluation.reason
    assert goal.assignment_id not in {
        g.assignment_id for g in store.load_supplemental_assignments()}
    restarted = ActivePlanCommitmentStore(store._path)
    assert restarted.load_supplemental_assignments() == store.load_supplemental_assignments()
    pipeline.run(planning_input=recover(source))
    assert goal.assignment_id not in {
        g.assignment_id for g in store.load_supplemental_assignments()}

def test_one_obsolete_goal_can_retire_while_another_bridge_remains(tmp_path, monkeypatch):
    from datetime import timedelta

    from picot.domain.execution_primitive import ExecutionPrimitive

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.3) for s in source.current_storage_states)))
    goal = store.load_supplemental_assignments()[0]
    context = snapshot.daily_charge_context
    plan = next(p for p in context.main_plans if p.plan_id == goal.plan_id)
    charge = next(s for s in plan.segments if s.segment_id in goal.segment_ids)
    earlier = goal.starts_at - timedelta(minutes=15)
    before = next(s for s in plan.segments if s.starts_at <= earlier < s.ends_at)
    extra = replace(charge, segment_id='earlier-supplement', starts_at=earlier,
                    ends_at=goal.starts_at, purpose='earlier-goal')
    replacement = []
    for segment in plan.segments:
        if segment != before:
            replacement.append(segment)
        else:
            if segment.starts_at < earlier:
                replacement.append(replace(segment, ends_at=earlier))
            replacement.append(extra)
            if goal.starts_at < segment.ends_at:
                replacement.append(replace(segment, segment_id=segment.segment_id + ':tail',
                                           starts_at=goal.starts_at))
    plan = replace(plan, segments=tuple(replace(s, order=n + 1)
                                       for n, s in enumerate(replacement)))
    other = replace(goal, assignment_id='earlier-goal', starts_at=earlier, ends_at=goal.starts_at,
                    target_soc=0.29, segment_ids=(extra.segment_id,))
    context = replace(context, main_plans=tuple(plan if p.plan_id == plan.plan_id else p
                                              for p in context.main_plans),
                      supplemental_assignments=(other, goal))
    snapshot = replace(snapshot, daily_charge_context=context)
    adapter = IndependentDailyReferenceAdapter()
    # Force the ordinary goal review by raising the old administrative target;
    # sufficient remaining charging must still be retained in its own right.
    inflated = replace(goal, target_soc=0.9)
    snapshot = replace(snapshot, daily_charge_context=replace(
        context, supplemental_assignments=(other, inflated)))
    assessment = adapter.bridge_assessment(snapshot=snapshot,
                                           conversion_model=inputs()['conversion_model'])
    assert assessment.trigger is not None
    windows = adapter.bridge_windows(snapshot=snapshot, trigger=assessment.trigger,
                                     conversion_model=inputs()['conversion_model'])
    selective = [w for w in windows.windows if w.supplemental_retirements == (goal.assignment_id,)]
    assert selective, [(w.schedule.schedule_id, w.invalidity_reasons,
                       [(i.ends_at.isoformat(), i.storage_energy_at_end_wh)
                        for i in w.projection.intervals if earlier <= i.ends_at <= goal.ends_at])
                      for w in windows.rejected_windows if 'retire' in w.schedule.schedule_id]
    assert all(other.assignment_id in {g.assignment_id for g in w.supplemental_assignments}
               for w in selective)
    assert extra.primitive is ExecutionPrimitive.CHARGE_AT_POWER


def test_retirement_requires_unchanged_and_fully_delivered_market_export(tmp_path, monkeypatch):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states)))
    goal = store.load_supplemental_assignments()[0]
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == goal.next_assignment_id)
    adapter = IndependentDailyReferenceAdapter()
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    physical = adapter._inputs(snapshot, horizon_end=plan.valid_until)
    baseline, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=physical, supplied=None)
    export = replace(baseline.intervals[0], intent=DailyStorageIntent.STORAGE_EXPORT,
                     storage_export_target_wh=100)
    schedule = replace(baseline, intervals=(export,) + baseline.intervals[1:])
    projection = adapter._bridge_projection(snapshot, physical, schedule,
                                            inputs()['conversion_model'])
    assert adapter._retirement_exports_valid(schedule, projection)
    assert adapter._same_exports(schedule, schedule)
    increased = replace(schedule, intervals=(replace(export, storage_export_target_wh=200),)
                        + schedule.intervals[1:])
    assert not adapter._retirement_exports_valid(increased, projection)
    assert not adapter._same_exports(schedule, increased)
    assert not adapter._same_exports(schedule, baseline)

def test_positive_earlier_pv_cannot_orphan_old_future_grid_command(tmp_path, monkeypatch):
    from picot.domain.daily_reference_charge_window import DailyMainChargeWindow
    from picot.v2.supplemental_charge_planning import attach_supplemental_goals

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    source = replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states),
        pv_energy_timeline=replace(source.pv_energy_timeline, intervals=tuple(
            replace(i, pv_energy_wh=1000, forecast_lower_energy_wh=1000,
                    forecast_central_energy_wh=1000, forecast_upper_energy_wh=1000)
            for i in source.pv_energy_timeline.intervals)))
    snapshot = recover(source)
    goal = store.load_supplemental_assignments()[0]
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == goal.next_assignment_id)
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    adapter = IndependentDailyReferenceAdapter()
    physical = adapter._inputs(snapshot, horizon_end=plan.valid_until)
    incumbent = adapter.main_charge_incumbent(snapshot=snapshot, assignment=owner,
        conversion_model=inputs()['conversion_model'], horizon_end=plan.valid_until)
    schedule = replace(incumbent.schedule, intervals=tuple(
        replace(i, intent=DailyStorageIntent.NOM)
        if i.ends_at <= goal.starts_at else i for i in incumbent.schedule.intervals))
    projection = adapter._bridge_projection(snapshot, physical, schedule,
                                            inputs()['conversion_model'])
    window = DailyMainChargeWindow(owner.assignment_id, incumbent.family, schedule,
        incumbent.main_segments, projection, incumbent.main_segments[0].starts_at,
        physical.target_storage_energy_wh, incumbent.retained_main_segments)
    assert any(i.storage_energy_at_end_wh > i.storage_energy_at_start_wh
               for i in projection.intervals if i.ends_at <= goal.starts_at)
    assert any(i.intent is DailyStorageIntent.GRID_REQUIREMENT
               for i in schedule.intervals if goal.starts_at <= i.starts_at < goal.ends_at)
    assert attach_supplemental_goals(window, snapshot) is None

def test_retirement_discovery_cannot_modify_incumbent_market_export(tmp_path, monkeypatch):
    from picot.v2.material_replanning import daily_grid_review_comparison

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    snapshot = recover(replace(source, current_storage_states=tuple(
        replace(s, current_soc=0.9) for s in source.current_storage_states)))
    goal = store.load_supplemental_assignments()[0]
    owner = next(a for a in snapshot.daily_charge_context.assignments
                 if a.assignment_id == goal.next_assignment_id)
    state = next(s for s in snapshot.daily_charge_context.pv_comparison_states
                 if s.assignment_id == owner.assignment_id)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()['conversion_model']
    comparison = replace(daily_grid_review_comparison(snapshot, state),
                         status='complete', actual_wh=100, central_wh=100)
    trigger = adapter.pv_surplus_trigger(snapshot=snapshot, assignment=owner,
                                         comparison=comparison, conversion_model=conversion)
    assert trigger is not None
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    physical = adapter._inputs(snapshot, horizon_end=plan.valid_until)
    baseline, _ = adapter._retained_main_schedule(
        snapshot=snapshot, assignment=owner, inputs=physical, supplied=None)
    changed_export = replace(baseline, intervals=(replace(
        baseline.intervals[0], intent=DailyStorageIntent.STORAGE_EXPORT,
        storage_export_target_wh=100),) + baseline.intervals[1:])
    groups = []
    original = adapter._retirement_groups

    def counted(goals):
        groups.append(goals)
        return original(goals)

    monkeypatch.setattr(adapter, '_retirement_groups', counted)
    altered = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
        conversion_model=conversion, optimisation_trigger=trigger, revision_schedule=changed_export)
    assert not groups
    assert all(not w.supplemental_retirements for w in altered.windows)
    unchanged = adapter.main_charge_windows(snapshot=snapshot, assignment=owner,
        conversion_model=conversion, optimisation_trigger=trigger, revision_schedule=baseline)
    assert groups
    assert any(w.supplemental_retirements for w in unchanged.windows)

    # The bridge path uses the same scope boundary, even when its review is
    # triggered by an administrative target rather than a new physical deficit.
    snapshot = replace(snapshot, daily_charge_context=replace(snapshot.daily_charge_context,
        supplemental_assignments=(replace(goal, target_soc=0.99),)))
    bridge = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion)
    assert bridge.trigger is not None
    groups.clear()
    altered = adapter.bridge_windows(snapshot=snapshot, trigger=bridge.trigger,
        conversion_model=conversion, revision_schedule=changed_export)
    assert not groups
    assert all(not w.supplemental_retirements for w in altered.windows)
    unchanged = adapter.bridge_windows(snapshot=snapshot, trigger=bridge.trigger,
        conversion_model=conversion, revision_schedule=baseline)
    assert groups
    assert any(w.supplemental_retirements for w in unchanged.windows)
