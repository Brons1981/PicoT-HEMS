"""Fresh HA state reads preserve old sensor timestamps at the main boundary."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup, with_mode

from picot.v2.canonical_execution_runtime import CanonicalExecutionRuntime
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("minutes_before", [0, 10])
def test_unchanged_full_state_at_main_start_completes_without_new_measurement(
    tmp_path,
    monkeypatch,
    restart,
    minutes_before,
):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    plan = store.load_active_daily_main_plan("battery")
    segment = next(s for s in plan.segments if s.main_assignment_id is not None)
    at = segment.starts_at + timedelta(seconds=1)
    measured = segment.starts_at - timedelta(minutes=minutes_before)
    source = replace(
        selected.planning_input,
        daily_charge_context=None,
        captured_at=at,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=at
        ),
        current_storage_states=tuple(
            replace(
                s,
                current_soc=1,
                measured_at=measured,
                state_valid_since=measured,
                state_read_at=at,
            )
            for s in selected.planning_input.current_storage_states
        ),
    )
    source = with_mode(source, segment.primitive, current_mode="Test active")
    if restart:
        store = ActivePlanCommitmentStore(tmp_path / "plans.json")
    runtime = CanonicalExecutionRuntime(
        lambda *a: (_ for _ in ()).throw(AssertionError("already active")), commitment_store=store
    )
    result = runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert result.status == "already_active"
    completed = store.load_daily_assignments()[0]
    assert completed.completed_at == at
    assert completed.completion_segment_id == segment.segment_id
    assert f"measured={measured.isoformat()}" in completed.completion_evidence_id
    assert source.current_storage_states[0].measured_at == measured
    assert (
        ActivePlanCommitmentStore(tmp_path / "plans.json").load_daily_assignments()[0] == completed
    )


@pytest.mark.parametrize("proof", ["absent", "read_before_start", "changed_after_start", "future"])
def test_unproven_old_full_state_cannot_complete(tmp_path, monkeypatch, proof):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    plan = store.load_active_daily_main_plan("battery")
    segment = next(s for s in plan.segments if s.main_assignment_id is not None)
    at = segment.starts_at + timedelta(seconds=10)
    since = segment.starts_at - timedelta(seconds=1)
    read = at
    if proof == "read_before_start":
        read = segment.starts_at - timedelta(seconds=1)
    if proof == "changed_after_start":
        since = segment.starts_at + timedelta(seconds=1)
    if proof == "future":
        read = at + timedelta(seconds=1)
    source = replace(
        selected.planning_input,
        daily_charge_context=None,
        captured_at=at,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=at
        ),
        current_storage_states=tuple(
            replace(
                s,
                current_soc=1,
                measured_at=since,
                state_valid_since=since if proof != "absent" else None,
                state_read_at=read if proof != "absent" else None,
            )
            for s in selected.planning_input.current_storage_states
        ),
    )
    source = with_mode(source, segment.primitive, current_mode="Test active")
    runtime = CanonicalExecutionRuntime(
        lambda *a: (_ for _ in ()).throw(AssertionError("already active")), commitment_store=store
    )
    runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert store.load_daily_assignments()[0].completed_at is None


def test_real_state_reader_preserves_measurement_time_and_records_read_proof(monkeypatch):
    import json
    from datetime import UTC, datetime

    from picot.v2 import planning_input as module

    old = datetime(2020, 1, 1, tzinfo=UTC)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "state": "100",
                    "attributes": {"unit_of_measurement": "%"},
                    "last_updated": old.isoformat(),
                    "last_changed": old.isoformat(),
                }
            ).encode()

    monkeypatch.setattr(module, "urlopen", lambda *a, **k: Response())
    source = module.HomeAssistantStateReader("test-token").read(
        module.SourceBinding("zendure", "storage_soc", "sensor.test_soc")
    )
    state = module._current_storage_states_from_evidence(
        (source,),
        config=module.StorageStateConfig("battery", "capability", 8160),
    )[0]
    assert state.measured_at == old
    assert state.state_valid_since == old
    assert state.state_read_at == source.state_read_at
    assert state.state_read_at > old
    assert state.current_soc == 1
    from picot.v2.pipeline import _bootstrap_snapshot
    from picot.v2.planning_incident_history import _entity_observations

    snapshot = _bootstrap_snapshot(state.state_read_at)
    bundle = module.PlanningInputBundle(
        snapshot=snapshot,
        evidence=(source,),
        facts=(),
        assembly_started_at=state.state_read_at,
        assembly_finished_at=state.state_read_at,
    )
    recorded = _entity_observations(bundle)[0]
    assert recorded["observed_at"] == old
    assert recorded["state_read_at"] == state.state_read_at


def test_new_state_proof_does_not_override_manual_execution_block(tmp_path, monkeypatch):
    store, pipeline, recover = setup(tmp_path, monkeypatch)
    selected = pipeline.run(planning_input=recover())
    plan = store.load_active_daily_main_plan("battery")
    segment = next(s for s in plan.segments if s.main_assignment_id is not None)
    at = segment.starts_at + timedelta(seconds=1)
    source = replace(
        selected.planning_input,
        daily_charge_context=None,
        captured_at=at,
        capability_snapshot_set=replace(
            selected.planning_input.capability_snapshot_set, captured_at=at
        ),
        current_storage_states=tuple(
            replace(
                s,
                current_soc=1,
                measured_at=segment.starts_at,
                state_valid_since=segment.starts_at,
                state_read_at=at,
            )
            for s in selected.planning_input.current_storage_states
        ),
    )
    source = with_mode(source, segment.primitive, current_mode="Test active")
    source = replace(
        source,
        storage_mode_control_provenance=replace(
            source.storage_mode_control_provenance,
            manual_override_active=True,
            status="manual_override",
        ),
    )
    runtime = CanonicalExecutionRuntime(
        lambda *a: (_ for _ in ()).throw(AssertionError("manual block")), commitment_store=store
    )
    runtime.advance_committed_boundary(recover(source), execution_enabled=True)
    assert store.load_daily_assignments()[0].completed_at is None
