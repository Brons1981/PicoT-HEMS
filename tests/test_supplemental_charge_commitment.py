"""ADR-037.10: supplemental charge has its own durable, measured goal."""

from dataclasses import replace

import pytest
from test_daily_bridge_pipeline import started


def charged(tmp_path, monkeypatch):
    store, pipeline, recover, source, completed, _ = started(tmp_path, monkeypatch)
    source = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.01 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    result = pipeline.run(planning_input=recover(source))
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    return store, pipeline, recover, source, completed


def test_charge_has_own_goal_and_restart_identity(tmp_path, monkeypatch):
    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, _, recover, source, completed = charged(tmp_path, monkeypatch)
    goals = store.load_supplemental_assignments()
    assert goals
    goal = goals[0]
    assert 0 < goal.target_soc <= 1
    assert goal.completed_at is None
    assert goal.assignment_id != goal.next_assignment_id
    assert goal.ends_at <= goal.required_by
    assert (
        ActivePlanCommitmentStore(tmp_path / "plans.json").load_supplemental_assignments() == goals
    )
    assert recover(source).daily_charge_context.supplemental_assignments == goals
    assert store.load_daily_assignments()[0] == completed


@pytest.mark.parametrize("full", [False, True])
def test_measured_target_completes_only_supplement_and_survives_restart(
    tmp_path, monkeypatch, full
):
    from picot.v2.plan_commitment_store import ActivePlanCommitmentStore

    store, _, _, _, completed = charged(tmp_path, monkeypatch)
    goal = store.load_supplemental_assignments()[0]
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    segment = next(s for s in plan.segments if s.segment_id == goal.segment_ids[-1])
    kwargs = dict(
        execution_scope_id=goal.execution_scope_id,
        plan_id=plan.plan_id,
        segment_id=segment.segment_id,
        confirmed_since=segment.starts_at,
        observed_at=segment.ends_at,
        measured_at=segment.ends_at,
        evidence_id="actual-soc",
    )
    assert store.observe_supplemental_completion(soc=goal.target_soc / 2, **kwargs) is None
    done = store.observe_supplemental_completion(soc=1 if full else goal.target_soc, **kwargs)
    assert done.completed_at == segment.ends_at
    assert done.assignment_id == goal.assignment_id
    assert store.load_daily_assignments()[0] == completed
    assert any(a.completed_at is None for a in store.load_daily_assignments())
    assert (
        ActivePlanCommitmentStore(tmp_path / "plans.json").load_supplemental_assignments()[0]
        == done
    )
    assert store.observe_supplemental_completion(soc=0.1, **kwargs) == done


def test_wrong_execution_and_old_observation_do_not_complete(tmp_path, monkeypatch):
    from datetime import timedelta

    store, _, _, _, _ = charged(tmp_path, monkeypatch)
    goal = store.load_supplemental_assignments()[0]
    kwargs = dict(
        execution_scope_id=goal.execution_scope_id,
        plan_id=goal.plan_id,
        segment_id=goal.segment_ids[0],
        confirmed_since=goal.starts_at,
        observed_at=goal.starts_at,
        measured_at=goal.starts_at - timedelta(seconds=1),
        evidence_id="old",
        soc=1,
    )
    assert store.observe_supplemental_completion(**kwargs) is None
    assert store.observe_supplemental_completion(**(kwargs | {"segment_id": "wrong"})) is None
    assert store.load_supplemental_assignments()[0].completed_at is None


def test_direct_grid_support_creates_no_fictitious_charge_goal(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch)
    pipeline.run(planning_input=recover(source))
    assert store.load_supplemental_assignments() == ()


def test_goal_is_retained_without_price_search(tmp_path, monkeypatch):
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    store, pipeline, recover, source, _ = charged(tmp_path, monkeypatch)
    before = store.load_supplemental_assignments()

    def forbidden(*args, **kwargs):
        raise AssertionError("new prices alone cannot replace supplemental commitment")

    monkeypatch.setattr(IndependentDailyReferenceAdapter, "bridge_windows", forbidden)
    updated = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.001 if p.starts_at.hour == 13 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    pipeline.run(planning_input=recover(updated))
    assert store.load_supplemental_assignments() == before


@pytest.mark.parametrize("manual_block", [False, True])
def test_runtime_confirms_supplemental_target_with_main_goal_still_open(
    tmp_path, monkeypatch, manual_block
):
    from datetime import timedelta

    from test_daily_main_active_pipeline import with_mode

    from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    goal = store.load_supplemental_assignments()[0]
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    segment = next(s for s in plan.segments if s.segment_id == goal.segment_ids[0])
    at = segment.starts_at + timedelta(seconds=1)
    observation = with_mode(
        replace(
            source,
            captured_at=at,
            capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
            current_storage_states=tuple(
                replace(s, current_soc=goal.target_soc, measured_at=at)
                for s in source.current_storage_states
            ),
        ),
        segment.primitive,
        current_mode="Test active",
    )
    if manual_block:
        observation = replace(
            observation,
            storage_mode_control_provenance=replace(
                observation.storage_mode_control_provenance,
                manual_override_active=True,
                status="manual_override",
            ),
        )
    runtime = CanonicalExecutionRuntime(
        lambda *args: (_ for _ in ()).throw(AssertionError("already active")),
        commitment_store=store,
    )
    result = runtime.advance_committed_boundary(recover(observation), execution_enabled=True)
    if manual_block:
        assert store.load_supplemental_assignments()[0].completed_at is None
    else:
        assert result.status == "already_active"
        assert store.load_supplemental_assignments()[0].completed_at == at
    assert any(a.completed_at is None for a in store.load_daily_assignments())


def test_corrupt_supplemental_binding_blocks_recovery(tmp_path, monkeypatch):
    import json

    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    payload = json.loads(store._path.read_text())
    goal = next(iter(payload["supplemental_assignments"].values()))
    goal["segment_ids"] = ["not-the-selected-segment"]
    store._path.write_text(json.dumps(payload))
    assert recover(source).daily_charge_context.status == "blocked"


def test_revision_candidates_keep_target_and_required_time(tmp_path, monkeypatch):
    from test_daily_main_charge_windows import inputs

    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter

    store, pipeline, recover, source, _ = charged(tmp_path, monkeypatch)
    original = store.load_supplemental_assignments()[0]
    changed = replace(
        source,
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(i, expected_energy_wh=i.expected_energy_wh * 1.1)
                for i in source.household_load_forecast.intervals
            ),
        ),
    )
    snapshot = recover(changed)
    adapter = IndependentDailyReferenceAdapter()
    assessment = adapter.bridge_assessment(
        snapshot=snapshot, conversion_model=inputs()["conversion_model"]
    )
    assert assessment.trigger is not None
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=assessment.trigger, conversion_model=inputs()["conversion_model"]
    )
    assert windows.windows
    for window in windows.windows:
        retained = next(
            a for a in window.supplemental_assignments if a.assignment_id == original.assignment_id
        )
        assert retained.target_soc == original.target_soc
        assert retained.required_by == original.required_by
        assert retained.ends_at <= original.required_by

    result = pipeline.run(planning_input=snapshot)
    assert result.evaluation.status == "winner_selected", result.evaluation.reason
    updated = next(
        a
        for a in store.load_supplemental_assignments()
        if a.assignment_id == original.assignment_id
    )
    assert updated.target_soc == original.target_soc
    assert updated.required_by == original.required_by
    assert updated.plan_id != original.plan_id
    assert updated.completed_at is None


def test_failed_supplemental_binding_leaves_no_half_assignment(tmp_path, monkeypatch):
    store, pipeline, recover, source, _, _ = started(tmp_path, monkeypatch)
    source = replace(
        source,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.01 if p.starts_at.hour == 11 else p.value_eur_per_kwh)
            for p in source.price_points
        ),
    )
    snapshot = recover(source)
    before = store._path.read_bytes()

    def failed(*args, **kwargs):
        raise OSError("test atomic write failure")

    monkeypatch.setattr(store, "_write", failed)
    result = pipeline.run(planning_input=snapshot)
    assert result.evaluation.status == "fallback_active"
    assert store._path.read_bytes() == before
    assert store.load_supplemental_assignments() == ()
