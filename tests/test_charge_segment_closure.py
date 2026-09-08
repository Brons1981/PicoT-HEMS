"""Late SOC samples retain the actual previous execution owner."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import with_mode
from test_supplemental_charge_commitment import charged

from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime


@pytest.mark.parametrize(
    "arrival", ["next_poll", "later_poll", "measured_after_end", "write_failure"]
)
def test_late_final_sample_closes_previous_supplement_before_dispatch(
    tmp_path, monkeypatch, arrival
):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    goal = store.load_supplemental_assignments()[0]
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    old = next(s for s in plan.segments if s.segment_id == goal.segment_ids[-1])
    runtime = CanonicalExecutionRuntime(
        lambda *a: CanonicalDispatchOutcome("dispatched", "test-only"), commitment_store=store
    )
    observations = [(-1, goal.target_soc / 2, -1), (1, goal.target_soc, 0)]
    if arrival == "later_poll":
        observations = [
            (-1, goal.target_soc / 2, -1),
            (1, goal.target_soc / 2, -1),
            (2, goal.target_soc, 0),
        ]
    if arrival == "measured_after_end":
        observations[-1] = (1, goal.target_soc, 0.5)
    for delta, soc, measured_delta in observations:
        at = old.ends_at + timedelta(seconds=delta)
        measured = old.ends_at + timedelta(seconds=measured_delta)
        # The previous mode remains physically observed while the next action is due.
        observation = with_mode(
            replace(
                source,
                captured_at=at,
                capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
                current_storage_states=tuple(
                    replace(s, current_soc=soc, measured_at=measured)
                    for s in source.current_storage_states
                ),
            ),
            old.primitive,
            current_mode="Test active",
        )
        observation = replace(
            observation,
            storage_mode_capability_evidence=replace(
                observation.storage_mode_capability_evidence, state_changed_at=old.starts_at
            ),
        )
        if arrival == "write_failure" and delta > 0:
            before = store._path.read_bytes()

            def failed(*args, **kwargs):
                raise OSError("test closing write failure")

            with monkeypatch.context() as blocked:
                blocked.setattr(store, "_write", failed)
                outcome = runtime.advance_committed_boundary(
                    recover(observation), execution_enabled=True
                )
                assert outcome.status == "blocked"
                assert "charge_completion_evidence_failed" in outcome.failure_reason
            assert store._path.read_bytes() == before
        runtime.advance_committed_boundary(recover(observation), execution_enabled=True)
    done = store.load_supplemental_assignments()[0]
    if arrival == "measured_after_end":
        assert done.completed_at is None
    else:
        assert done.completed_at == old.ends_at
        assert old.ends_at.isoformat() in done.completion_evidence_id
    assert any(a.completed_at is None for a in store.load_daily_assignments())


@pytest.mark.parametrize(
    "proof", ["changed_at_end", "missing", "changed_before_sample", "manual", "restart"]
)
def test_changed_mode_requires_transition_proof(tmp_path, monkeypatch, proof):
    store, _, recover, source, _ = charged(tmp_path, monkeypatch)
    goal = store.load_supplemental_assignments()[0]
    plan = store.load_active_daily_main_plan(goal.execution_scope_id)
    old = next(s for s in plan.segments if s.segment_id == goal.segment_ids[-1])
    runtime = CanonicalExecutionRuntime(
        lambda *a: CanonicalDispatchOutcome("dispatched", "test-only"), commitment_store=store
    )
    for delta, soc in [(-1, goal.target_soc / 2), (1, goal.target_soc)]:
        at = old.ends_at + timedelta(seconds=delta)
        observed = with_mode(
            replace(
                source,
                captured_at=at,
                capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
                current_storage_states=tuple(
                    replace(s, current_soc=soc, measured_at=min(at, old.ends_at))
                    for s in source.current_storage_states
                ),
            ),
            old.primitive,
            current_mode="Test active" if delta < 0 else "Next active",
        )
        if delta > 0:
            changed = old.ends_at if proof != "missing" else None
            if proof == "changed_before_sample":
                changed = old.ends_at - timedelta(microseconds=1)
            observed = replace(
                observed,
                storage_mode_capability_evidence=replace(
                    observed.storage_mode_capability_evidence, state_changed_at=changed
                ),
            )
            if proof == "manual":
                observed = replace(
                    observed,
                    storage_mode_control_provenance=replace(
                        observed.storage_mode_control_provenance,
                        status="manual_override",
                        manual_override_active=True,
                    ),
                )
            if proof == "restart":
                runtime = CanonicalExecutionRuntime(
                    lambda *a: CanonicalDispatchOutcome("dispatched", "test-only"),
                    commitment_store=store,
                )
        runtime.advance_committed_boundary(recover(observed), execution_enabled=True)
    assert (store.load_supplemental_assignments()[0].completed_at is not None) == (
        proof == "changed_at_end"
    )


def test_late_main_sample_completes_only_original_main(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import setup

    store, pipeline, recover = setup(tmp_path, monkeypatch)
    first = pipeline.run(planning_input=recover())
    source = replace(first.planning_input, daily_charge_context=None)
    plan = store.load_active_daily_main_plan("battery")
    owner = store.load_daily_assignments()[0]
    old = next(s for s in plan.segments if s.segment_id == owner.main_segments[-1].segment_id)
    runtime = CanonicalExecutionRuntime(
        lambda *a: CanonicalDispatchOutcome("dispatched", "test-only"), commitment_store=store
    )
    for delta, soc in [(-1, 0.9), (1, 1.0)]:
        at = old.ends_at + timedelta(seconds=delta)
        observed = with_mode(
            replace(
                source,
                captured_at=at,
                capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
                current_storage_states=tuple(
                    replace(s, current_soc=soc, measured_at=min(at, old.ends_at))
                    for s in source.current_storage_states
                ),
            ),
            old.primitive,
            current_mode="Test active",
        )
        observed = replace(
            observed,
            storage_mode_capability_evidence=replace(
                observed.storage_mode_capability_evidence, state_changed_at=old.starts_at
            ),
        )
        runtime.advance_committed_boundary(recover(observed), execution_enabled=True)
    done = store.load_daily_assignments()[0]
    assert done.assignment_id == owner.assignment_id
    assert done.completed_at == old.ends_at
    assert runtime.completion_generation > 0


def test_poll_captures_fresh_input_after_proven_completion():
    from test_v2_live_replan_poll_cycle import BASE, _bundle

    from picot.v2.live_runtime import _poll_live_cycle

    before = _bundle(captured_at=BASE, price=0.2)
    after = _bundle(captured_at=BASE + timedelta(seconds=1), price=0.2)
    bundles = iter((before, after))
    executed = []
    advanced = []
    prepared = []

    def advance(bundle):
        advanced.append(bundle.snapshot.snapshot_id)
        return True

    def prepare(bundle):
        prepared.append(bundle.snapshot.snapshot_id)
        return bundle, None

    _poll_live_cycle(
        previous_signature=None,
        load_bundle=lambda: next(bundles),
        advance_clock_boundaries=advance,
        prepare_bundle=prepare,
        execute=lambda bundle, diagnostics: executed.append(bundle.snapshot.snapshot_id),
    )
    assert advanced == [before.snapshot.snapshot_id]
    assert prepared == [before.snapshot.snapshot_id, after.snapshot.snapshot_id]
    assert executed == [after.snapshot.snapshot_id]
    assert before.snapshot.captured_at == BASE


def test_mode_reader_keeps_actual_transition_timestamp():
    from datetime import UTC, datetime

    from picot.v2.zendure_mode_capabilities import derive_zendure_mode_capability_evidence

    at = datetime(2026, 9, 8, 12, 0, 1, tzinfo=UTC)
    result = derive_zendure_mode_capability_evidence(
        {
            "state": "Nul op de meter",
            "last_changed": "2026-09-08T12:00:00Z",
            "attributes": {"options": ["Nul op de meter", "Snel opladen"]},
        },
        captured_at=at,
        source_entity_id="input_select.mode",
        capability_id="battery",
        execution_scope_id="battery",
    )
    assert result.state_changed_at == at - timedelta(seconds=1)
