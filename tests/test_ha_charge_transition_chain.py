"""Dispatch, persisted HA feedback and late SOC proof in one poll sequence."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_daily_main_active_pipeline import setup
from test_supplemental_charge_commitment import charged

from picot.v2.canonical_execution_runtime import CanonicalDispatchOutcome, CanonicalExecutionRuntime
from picot.v2.live_runtime import _poll_live_cycle
from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
    attach_storage_mode_provenance,
)
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.zendure_mode_capabilities import (
    ZendureModeMapping,
    derive_zendure_mode_capability_evidence,
)


@pytest.mark.parametrize(
    "kind,condition",
    [
        ("main", "normal"),
        ("supplemental", "normal"),
        ("supplemental", "manual"),
        ("supplemental", "late_measurement"),
    ],
)
def test_poll_dispatch_feedback_and_completion(tmp_path, monkeypatch, kind, condition):
    if kind == "main":
        store, pipeline, recover = setup(tmp_path, monkeypatch)
        first = pipeline.run(planning_input=recover())
        source = replace(first.planning_input, daily_charge_context=None)
        goal = store.load_daily_assignments()[0]
        plan = store.load_active_daily_main_plan("battery")
        old = next(s for s in plan.segments if s.segment_id == goal.main_segments[-1].segment_id)
        target = 1.0
    else:
        store, _, recover, source, _ = charged(tmp_path, monkeypatch)
        goal = store.load_supplemental_assignments()[0]
        plan = store.load_active_daily_main_plan(goal.execution_scope_id)
        old = next(s for s in plan.segments if s.segment_id == goal.segment_ids[-1])
        target = goal.target_soc
    following = next(s for s in plan.segments if s.starts_at == old.ends_at)
    assert following.primitive != old.primitive
    initial_main = store.load_daily_assignments()
    provenance = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(tmp_path / "mode.json")
    )
    provenance.observe_vendor_mode("Snel opladen", observed_at=old.starts_at)
    provenance.record_planner_application(
        "Snel opladen", applied_at=old.starts_at, application_id="previous-charge"
    )
    dispatched = []

    def dispatch(request, mapping):
        dispatched.append(request)
        return CanonicalDispatchOutcome("dispatched", "test-command")

    runtime = CanonicalExecutionRuntime(dispatch, commitment_store=store)
    outcomes = []
    inputs = []
    loads = []
    current = None

    def load():
        loads.append(current.snapshot.captured_at)
        return current

    def prepare(bundle):
        bundle = attach_storage_mode_provenance(bundle, provenance)
        return replace(bundle, snapshot=recover(bundle.snapshot)), None

    def advance(bundle):
        before = runtime.completion_generation
        outcome = runtime.advance_committed_boundary(bundle.snapshot, execution_enabled=True)
        outcomes.append(outcome.status)
        if outcome.status == "dispatched":
            provenance.record_planner_application(
                outcome.planned_vendor_mode,
                applied_at=bundle.snapshot.captured_at,
                application_id=outcome.application_id,
            )
        return runtime.completion_generation != before

    for second in (-1, 1, 2, 3):
        at = old.ends_at + timedelta(seconds=second)
        mode = "Nul op de meter" if second == 3 else "Snel opladen"
        changed = old.ends_at + timedelta(seconds=2.5) if second == 3 else old.starts_at
        if condition == "manual" and second == 2:
            mode, changed = "Standby", at
        measured = old.ends_at if second == 3 else old.ends_at - timedelta(seconds=1)
        if condition == "late_measurement" and second == 3:
            measured += timedelta(microseconds=1)
        evidence = derive_zendure_mode_capability_evidence(
            {
                "state": mode,
                "last_changed": changed.isoformat(),
                "attributes": {"options": ["Snel opladen", "Nul op de meter", "Standby"]},
            },
            captured_at=at,
            source_entity_id="input_select.test_mode",
            capability_id=old.capability_id,
            execution_scope_id=plan.execution_scope_id,
        )
        evidence = replace(
            evidence,
            mappings=(
                ZendureModeMapping(
                    "Snel opladen", (old.primitive,), "integration_configured_maximum"
                ),
                ZendureModeMapping(
                    "Nul op de meter", (following.primitive,), "integration_configured_maximum"
                ),
            ),
        )
        snapshot = replace(
            source,
            captured_at=at,
            capability_snapshot_set=replace(source.capability_snapshot_set, captured_at=at),
            current_storage_states=tuple(
                replace(s, measured_at=measured, current_soc=target if second == 3 else target / 2)
                for s in source.current_storage_states
            ),
            storage_mode_capability_evidence=evidence,
            storage_mode_control_provenance=None,
        )
        current = PlanningInputBundle(
            snapshot=snapshot,
            evidence=(),
            facts=(),
            assembly_started_at=at,
            assembly_finished_at=at,
        )
        _poll_live_cycle(
            previous_signature=None,
            load_bundle=load,
            prepare_bundle=prepare,
            advance_clock_boundaries=advance,
            execute=lambda bundle, diagnostics: inputs.append(bundle.snapshot),
        )
    done = next(
        a
        for a in (
            store.load_daily_assignments()
            if kind == "main"
            else store.load_supplemental_assignments()
        )
        if a.assignment_id == goal.assignment_id
    )
    assert len(dispatched) == 1
    assert outcomes[:2] == ["already_active", "dispatched"]
    if condition == "normal":
        assert outcomes[2:] == ["awaiting_mode_feedback", "already_active"]
        assert done.completed_at == old.ends_at
        assert len(loads) == 5  # Completion causes one fresh capture before planning.
        restored = inputs[-1].daily_charge_context
        visible = restored.assignments if kind == "main" else restored.supplemental_assignments
        assert (
            next(a for a in visible if a.assignment_id == goal.assignment_id).completed_at
            == old.ends_at
        )
    else:
        assert done.completed_at is None
        assert len(loads) == 4
    if kind == "supplemental":
        assert store.load_daily_assignments() == initial_main
