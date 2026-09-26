"""Explicit selected market changes preserve daily and execution ownership."""

from dataclasses import replace
from datetime import timedelta

import pytest

from picot.domain.market_plan_binding import MarketPlanBinding


def test_cancelled_volume_is_distinct_from_elapsed_and_remaining():
    binding = MarketPlanBinding(
        "day", "battery", "plan", "snapshot", ("remaining",), 100,
        (40,), elapsed_planned_export_wh=20, cancelled_export_wh=40,
    )
    assert binding.approved_export_wh == 60
    assert binding.elapsed_planned_export_wh == 20
    with pytest.raises(ValueError, match="complete export allocation"):
        replace(binding, cancelled_export_wh=39)


def test_legacy_binding_has_no_cancelled_volume():
    binding = MarketPlanBinding("day", "battery", "plan", "snapshot", ("segment",), 100, (100,))
    assert binding.cancelled_export_wh == 0
    assert binding.approved_export_wh == 100


def selected_revision(tmp_path, monkeypatch, *, change="shorten", begun=False, future=False):
    """Real simulated/selected/built path; economic preference is tested elsewhere."""
    from test_daily_bridge_pipeline import started
    from test_daily_main_charge_windows import inputs
    from test_market_plan_binding import proposal

    from picot.domain.daily_reference_intent import DailyStorageIntent
    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.domain.market_execution import MarketExecutionProgress
    from picot.planner.evaluation_engine import EvaluationEngine
    from picot.planner.execution_plan_builder import ExecutionPlanBuilder
    from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
    from picot.v2.daily_bridge import energy_deficits
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter
    from picot.v2.market_plan_revision import build_market_plan_revisions

    store, _, recover, source, completed, _ = started(tmp_path, monkeypatch)
    incumbent = store.load_active_daily_main_plan("battery")
    proposed = proposal(store, incumbent)
    if future:
        parts = []
        for segment in proposed["plan"].segments:
            if segment.segment_id in proposed["binding"].segment_ids:
                starts_at = segment.starts_at + timedelta(minutes=1)
                source_part = next(s for s in incumbent.segments
                                   if s.starts_at <= segment.starts_at < s.ends_at)
                parts.append(replace(source_part, segment_id="before-market", ends_at=starts_at))
                segment = replace(segment, starts_at=starts_at)
            parts.append(segment)
        proposed["plan"] = replace(proposed["plan"], segments=tuple(
            replace(s, order=i) for i, s in enumerate(parts, 1)
        ))
    store.bind_market_plan(**proposed)
    old = proposed["binding"]
    original = proposed["plan"]
    trade = next(s for s in original.segments if s.segment_id in old.segment_ids)
    at = trade.starts_at + timedelta(minutes=5) if begun else source.captured_at
    if begun:
        store.save_market_progress(MarketExecutionProgress(
            old.assignment_id, started_at=trade.starts_at, measured_export_wh=7,
        ))
    source = replace(
        source, captured_at=at,
        capability_snapshot_set=replace(
            source.capability_snapshot_set, captured_at=at,
            capabilities=tuple(replace(c, supported_primitives=(
                *c.supported_primitives, ExecutionPrimitive.DISCHARGE_AT_POWER,
            )) for c in source.capability_snapshot_set.capabilities),
        ),
        current_storage_states=tuple(replace(s, current_soc=0.2, measured_at=at)
                                     for s in source.current_storage_states),
    )
    snapshot = recover(source)
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    assert trigger is not None
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion,
    )
    baseline = next(w for w in windows.windows if any(
        i.intent is DailyStorageIntent.STORAGE_EXPORT for i in w.schedule.intervals
    ))
    exports = [i for i in baseline.schedule.intervals
               if i.intent is DailyStorageIntent.STORAGE_EXPORT]
    removed = exports if change == "remove" else exports[1:] if change == "shorten" else []
    if change == "shorten":
        assert len(exports) >= 2
    schedule = replace(
        baseline.schedule, schedule_id="store-revision:" + change,
        intervals=tuple(replace(i, intent=DailyStorageIntent.NOM, storage_export_target_wh=0)
                        if i in removed else i for i in baseline.schedule.intervals),
    )
    physical = adapter._bridge_projection(
        snapshot, adapter._inputs(snapshot, horizon_end=schedule.horizon_end), schedule, conversion,
    )
    window = replace(baseline, schedule=schedule, projection=physical)
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=replace(windows, windows=(window,)),
        tariffs=IndependentDailyTariffAdapter().build(snapshot, horizon_end=schedule.horizon_end),
        opportunity_ids=(),
    )
    evaluation = EvaluationEngine().evaluate(
        portfolio.candidate_set, portfolio.strategy, portfolio.outcome_set, created_at=at,
    )
    assert evaluation.winning_candidate is not None, evaluation.record.invalid_candidates
    plan = ExecutionPlanBuilder().build(
        evaluation, created_at=at, fallback_policy_id="guarded-nom",
    ).plans[0]
    revisions = build_market_plan_revisions(
        snapshot=snapshot, plan=plan, window=window, evaluation_record=evaluation.record,
    )
    return store, snapshot, completed, old, dict(
        plan=plan, window=window, activate=True, optimisation_trigger=trigger,
        market_revisions=revisions,
        bridge_deficits=energy_deficits(
            window.projection, window.schedule, until=trigger.next_starts_at,
            maximum_discharge_output_power_w=2400,
        ),
    )


@pytest.mark.parametrize("change", ["retain", "shorten", "remove"])
def test_explicit_revision_is_atomic_idempotent_and_survives_restart(
    tmp_path, monkeypatch, change,
):
    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, _, completed, old, args = selected_revision(tmp_path, monkeypatch, change=change)
    revised = store.bind_daily_main_plan(**args)
    path = tmp_path / "plans.json"
    before = path.read_bytes()
    assert store.bind_daily_main_plan(**args) == revised
    assert path.read_bytes() == before
    restarted = ActivePlanCommitmentStore(path)
    assert restarted.load_active_daily_main_plan("battery") == args["plan"]
    assert restarted.load_daily_assignments()[0] == completed
    binding, = restarted.load_market_plan_bindings()
    assignment, = restarted.load_market_daily_assignments()
    assert assignment.assignment_id == old.assignment_id
    assert assignment.battery_energy_wh == 2040
    if change == "remove":
        # This fixture is already at the scheduled start: absence of a start
        # observation cannot establish that the device never exported.
        assert assignment.status == "pending"
        assert assignment.measured_export_wh is None
        assert restarted.load_market_progress(old.assignment_id).stop_requested_at is not None
        assert binding == old  # Historical measurement owner, never a zero binding.
    else:
        assert assignment.status == "pending"
        assert binding.plan_id == args["plan"].plan_id
        assert binding.expected_export_wh == old.expected_export_wh
        # Fixture starts at 10:00:05; shortening keeps only until 10:15:00.
        assert binding.cancelled_export_wh == pytest.approx(
            100 * 905 / 1800 if change == "shorten" else 0
        )
        assert binding.elapsed_planned_export_wh == 0


def test_revision_requires_evidence_and_write_failure_keeps_exact_previous_state(
    tmp_path, monkeypatch,
):
    import os

    store, _, _, _, args = selected_revision(tmp_path, monkeypatch)
    path = tmp_path / "plans.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="removed or relocated"):
        store.bind_daily_main_plan(**(args | {"market_revisions": ()}))
    assert path.read_bytes() == before

    def fail(*args):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="atomic replace failed"):
        store.bind_daily_main_plan(**args)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["previous_active_plan_id", "winning_energy_path_id"])
def test_stale_or_wrong_selected_revision_cannot_publish(tmp_path, monkeypatch, field):
    store, _, _, _, args = selected_revision(tmp_path, monkeypatch)
    before = (tmp_path / "plans.json").read_bytes()
    revision, = args["market_revisions"]
    args["market_revisions"] = (replace(revision, **{field: "wrong"}),)
    with pytest.raises(ValueError, match="market revision"):
        store.bind_daily_main_plan(**args)
    assert (tmp_path / "plans.json").read_bytes() == before


def test_begun_removal_preserves_measurement_and_waits_for_actual_stop(tmp_path, monkeypatch):
    store, _, _, old, args = selected_revision(tmp_path, monkeypatch, change="remove", begun=True)
    previous = store.load_market_progress(old.assignment_id)
    store.bind_daily_main_plan(**args)
    progress = store.load_market_progress(old.assignment_id)
    assert progress.started_at == previous.started_at
    assert progress.measured_export_wh == 7
    assert progress.stop_requested_at == args["plan"].created_at
    assert progress.stopped_at is None
    assert store.load_market_daily_assignments()[0].status == "pending"
    store.save_market_progress(replace(
        progress, stopped_at=progress.stop_requested_at + timedelta(seconds=2),
        measured_export_wh=8,
    ))
    closed, = store.load_market_daily_assignments()
    assert closed.status == "stopped" and closed.measured_export_wh == 8


def test_future_removal_closes_skipped_without_export_measurement(tmp_path, monkeypatch):
    store, _, _, old, args = selected_revision(
        tmp_path, monkeypatch, change="remove", future=True,
    )
    store.bind_daily_main_plan(**args)
    assignment, = store.load_market_daily_assignments()
    assert assignment.status == "skipped"
    assert assignment.measured_export_wh is None
    assert store.load_market_plan_bindings() == (old,)
    assert store.ensure_market_daily_assignment(replace(
        assignment, rule=replace(assignment.rule, revision=assignment.rule.revision + 1),
    )) == assignment


@pytest.mark.parametrize("export_confirmed", [True, False])
def test_due_removal_waits_for_actual_mode_before_classifying_execution(
    tmp_path, monkeypatch, export_confirmed,
):
    from test_daily_main_active_pipeline import with_mode
    from test_market_execution_guard import history

    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.v2.market_execution_guard import guarded_market_primitive

    store, snapshot, _, old, args = selected_revision(tmp_path, monkeypatch, change="remove")
    store.bind_daily_main_plan(**args)
    assert store.load_market_daily_assignments()[0].status == "pending"
    snapshot = with_mode(
        snapshot, ExecutionPrimitive.DISCHARGE_AT_POWER,
        current_mode="Export" if export_confirmed else "NOM",
    )
    observed = replace(snapshot, market_power_history=history(
        snapshot.captured_at, snapshot.captured_at,
    ))
    guarded_market_primitive(
        snapshot=observed, store=store, scope_id="battery",
        requested=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=export_confirmed,
    )
    assignment, = store.load_market_daily_assignments()
    progress = store.load_market_progress(old.assignment_id)
    assert assignment.status == ("pending" if export_confirmed else "skipped")
    assert (progress.started_at is not None) == export_confirmed
    assert progress.stopped_at is None


def test_shortened_execution_stops_at_revised_end_and_preserves_original_measurement_start(
    tmp_path, monkeypatch,
):
    from test_market_execution_guard import history

    from picot.domain.execution_primitive import ExecutionPrimitive
    from picot.domain.market_execution import MarketExecutionProgress
    from picot.v2.market_execution_guard import guarded_market_primitive

    store, snapshot, _, old, args = selected_revision(tmp_path, monkeypatch, begun=True)
    previous = store.load_market_progress(old.assignment_id)
    store.bind_daily_main_plan(**args)
    binding, = store.load_market_plan_bindings()
    # Five minutes of planned volume passed; actual observation remains 7 Wh.
    assert binding.elapsed_planned_export_wh == pytest.approx(100 / 6)
    assert binding.cancelled_export_wh == pytest.approx(100 * 905 / 1800)
    assert store.load_market_progress(old.assignment_id) == previous
    parts = [s for s in args["plan"].segments if s.segment_id in binding.segment_ids]
    end = parts[-1].ends_at
    original = store.load_market_original_plan(binding)
    assert end < next(s.ends_at for s in original.segments if s.segment_id in old.segment_ids)
    store.save_market_progress(MarketExecutionProgress(
        old.assignment_id, started_at=previous.started_at, measured_export_wh=7,
    ))
    guarded_market_primitive(
        snapshot=replace(
            snapshot, captured_at=end, daily_charge_context=None,
            capability_snapshot_set=replace(snapshot.capability_snapshot_set, captured_at=end),
            market_power_history=history(previous.started_at, end, battery=1, export=1),
        ),
        store=store, scope_id="battery", requested=ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        export_mode_confirmed=True,
    )
    progress = store.load_market_progress(old.assignment_id)
    assert progress.started_at == previous.started_at
    assert progress.stop_requested_at == end
    assert progress.reason == "market_window_ended"
    assert progress.stopped_at is None


def test_restart_rejects_corrupted_selected_market_evidence(tmp_path, monkeypatch):
    import json

    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, _, _, _, args = selected_revision(tmp_path, monkeypatch)
    store.bind_daily_main_plan(**args)
    path = tmp_path / "plans.json"
    payload = json.loads(path.read_text())
    evidence = payload["market_plan_revisions"][args["plan"].plan_id][0]["evidence"]
    evidence["evaluation_record"]["winning_candidate_id"] = "someone-else"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid stored market revision history"):
        ActivePlanCommitmentStore(path).load_market_plan_bindings()


def test_retained_bridge_assessment_changes_only_assessment_and_is_idempotent(
    tmp_path, monkeypatch,
):
    import json

    store, snapshot, _, _, args = selected_revision(tmp_path, monkeypatch, change="retain")
    path = tmp_path / "plans.json"
    before = json.loads(path.read_text())
    revision, = args["market_revisions"]
    evidence = dict(
        trigger=args["optimisation_trigger"], snapshot_id=snapshot.snapshot_id,
        assessed_at=snapshot.captured_at, deficits=args["bridge_deficits"],
        evaluation_record=revision.evaluation_record,
    )
    store.record_retained_bridge_assessment(**evidence)
    after = json.loads(path.read_text())
    state = after.pop("daily_bridge_states")
    before.pop("daily_bridge_states", None)
    assert after == before
    assert state[args["window"].assignment_id]["plan_id"] == revision.previous_active_plan_id
    written = path.read_bytes()
    store.record_retained_bridge_assessment(**evidence)
    assert path.read_bytes() == written
    with pytest.raises(ValueError):
        store.record_retained_bridge_assessment(**(evidence | {"snapshot_id": "stale"}))
    assert path.read_bytes() == written
