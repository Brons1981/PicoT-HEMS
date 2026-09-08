"""Actual HA transition timestamps distinguish stale feedback from override."""

from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.live_storage_mode_provenance import (
    LiveStorageModeProvenanceRuntime,
    StorageModeProvenanceStore,
)

BASE = datetime(2026, 9, 8, 12, tzinfo=UTC)


@pytest.mark.parametrize("restart", [False, True])
def test_unchanged_feedback_waits_then_confirms(tmp_path, restart):
    store = StorageModeProvenanceStore(tmp_path / "provenance.json")
    runtime = LiveStorageModeProvenanceRuntime(store)
    runtime.observe_vendor_mode("Snel opladen", observed_at=BASE)
    runtime.record_planner_application(
        "Nul op de meter", applied_at=BASE + timedelta(seconds=1), application_id="request-1"
    )
    for second in (2, 3):
        if restart:
            runtime = LiveStorageModeProvenanceRuntime(store)
        state = runtime.observe_vendor_mode(
            "Snel opladen",
            observed_at=BASE + timedelta(seconds=second),
            state_changed_at=BASE - timedelta(minutes=1),
        )
        assert not state.manual_override_active
        assert state.transition_reason == "planner_application_awaiting_mode_feedback"
        assert state.last_planner_application_id == "request-1"
    state = runtime.observe_vendor_mode(
        "Nul op de meter",
        observed_at=BASE + timedelta(seconds=4),
        state_changed_at=BASE + timedelta(seconds=3),
    )
    assert not state.manual_override_active
    assert state.transition_reason == "observed_mode_matches_planner_mode"
    state = runtime.observe_vendor_mode(
        "Snel opladen",
        observed_at=BASE + timedelta(seconds=5),
        state_changed_at=BASE + timedelta(seconds=5),
    )
    assert state.manual_override_active


@pytest.mark.parametrize(
    "mode,changed",
    [
        ("Snel opladen", BASE + timedelta(seconds=2)),
        ("Standby", BASE + timedelta(seconds=2)),
        ("Snel opladen", None),
    ],
)
def test_changed_or_unproven_old_mode_still_blocks(tmp_path, mode, changed):
    runtime = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(tmp_path / "provenance.json")
    )
    runtime.observe_vendor_mode("Snel opladen", observed_at=BASE)
    runtime.record_planner_application(
        "Nul op de meter", applied_at=BASE + timedelta(seconds=1), application_id="request-1"
    )
    state = runtime.observe_vendor_mode(
        mode, observed_at=BASE + timedelta(seconds=3), state_changed_at=changed
    )
    assert state.manual_override_active
    state = runtime.observe_vendor_mode(
        "Nul op de meter",
        observed_at=BASE + timedelta(seconds=4),
        state_changed_at=BASE + timedelta(seconds=4),
    )
    assert state.manual_override_active


def test_live_attachment_passes_raw_ha_transition_evidence(tmp_path):
    from dataclasses import replace

    from test_v2_live_storage_mode_provenance import _bundle

    from picot.v2.live_storage_mode_provenance import attach_storage_mode_provenance
    from picot.v2.zendure_mode_capabilities import derive_zendure_mode_capability_evidence

    runtime = LiveStorageModeProvenanceRuntime(
        StorageModeProvenanceStore(tmp_path / "provenance.json")
    )

    def bundle_at(mode, at):
        bundle = _bundle(mode=mode)
        snapshot = bundle.snapshot
        return replace(
            bundle,
            snapshot=replace(
                snapshot,
                captured_at=at,
                capability_snapshot_set=replace(snapshot.capability_snapshot_set, captured_at=at),
                storage_mode_capability_evidence=replace(
                    snapshot.storage_mode_capability_evidence, captured_at=at
                ),
            ),
        )

    initial = bundle_at("Snel opladen", BASE)
    attach_storage_mode_provenance(initial, runtime)
    runtime.record_planner_application(
        "Nul op de meter", applied_at=BASE + timedelta(seconds=1), application_id="live-request"
    )
    for second, mode in [(2, "Snel opladen"), (3, "Nul op de meter")]:
        bundle = bundle_at(mode, BASE + timedelta(seconds=second))
        source = bundle.snapshot.storage_mode_capability_evidence
        evidence = derive_zendure_mode_capability_evidence(
            {
                "state": mode,
                "last_changed": (BASE if second == 2 else BASE + timedelta(seconds=3)).isoformat(),
                "attributes": {"options": ["Snel opladen", "Nul op de meter"]},
            },
            captured_at=bundle.snapshot.captured_at,
            source_entity_id=source.source_entity_id,
            capability_id=source.capability_id,
            execution_scope_id=source.execution_scope_id,
        )
        enriched = attach_storage_mode_provenance(
            replace(
                bundle, snapshot=replace(bundle.snapshot, storage_mode_capability_evidence=evidence)
            ),
            runtime,
        )
        assert not enriched.snapshot.storage_mode_control_provenance.manual_override_active
        assert enriched.snapshot.storage_mode_control_provenance.transition_reason == (
            "planner_application_awaiting_mode_feedback"
            if second == 2
            else "observed_mode_matches_planner_mode"
        )
