from dataclasses import replace
from datetime import timedelta

from test_v2_delegated_storage_pipeline_integration import BASE, _snapshot

from picot.domain.capability_snapshot import CapabilityAvailability
from picot.v2.live_runtime import _restore_active_plan_commitments
from picot.v2.plan_commitment_store import (
    LEGACY_COMMITMENT_METHOD_VERSION,
    PREVIOUS_COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)


def _commitment() -> ActivePlanCommitment:
    return ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="plan-restart",
        plan_revision=2,
        primitive="balance_charge_only",
        source_policy="pv_only",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=1),
        target_energy_wh=1200.0,
    )


def _at(captured_at):
    source = _snapshot()
    return replace(
        source,
        captured_at=captured_at,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            captured_at=captured_at,
        ),
    )


def test_restart_just_before_window_end_restores_commitment(tmp_path) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    store.save(_commitment())
    snapshot = _at(BASE + timedelta(hours=1, seconds=-1))

    restored = _restore_active_plan_commitments(snapshot, store)

    assert restored.active_plan_commitments == (_commitment(),)


def test_restart_before_future_window_restores_scheduled_commitment(tmp_path) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    future = replace(
        _commitment(),
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=2),
    )
    store.save(future)

    restored = _restore_active_plan_commitments(_at(BASE), store)

    assert restored.active_plan_commitments == (future,)


def test_legacy_commitment_is_cleared_for_household_replanning(tmp_path) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    store.save(
        replace(
            _commitment(),
            selection_method_version=LEGACY_COMMITMENT_METHOD_VERSION,
        )
    )

    restored = _restore_active_plan_commitments(_at(BASE), store)

    assert restored.active_plan_commitments == ()
    assert store.load("home-battery") is None
    assert "legacy_commitment_requires_household_replan" in (
        incidents.read_text(encoding="utf-8")
    )


def test_future_pre_subwindow_commitment_is_cleared_for_fresh_mep_plan(
    tmp_path,
) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    future = replace(
        _commitment(),
        starts_at=BASE + timedelta(hours=1),
        ends_at=BASE + timedelta(hours=2),
        selection_method_version=PREVIOUS_COMMITMENT_METHOD_VERSION,
    )
    store.save(future)

    restored = _restore_active_plan_commitments(_at(BASE), store)

    assert restored.active_plan_commitments == ()
    assert store.load("home-battery") is None
    assert "superseded_future_commitment_requires_replan" in (
        incidents.read_text(encoding="utf-8")
    )


def test_active_pre_subwindow_commitment_remains_fixed_until_phase_end(
    tmp_path,
) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    active = replace(
        _commitment(),
        selection_method_version=PREVIOUS_COMMITMENT_METHOD_VERSION,
    )
    store.save(active)

    restored = _restore_active_plan_commitments(
        _at(BASE + timedelta(minutes=15)),
        store,
    )

    assert restored.active_plan_commitments == (active,)


def test_expired_commitment_is_cleared_and_reported_at_restart(tmp_path) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    store.save(_commitment())

    restored = _restore_active_plan_commitments(
        _at(BASE + timedelta(hours=1)),
        store,
    )

    assert restored.active_plan_commitments == ()
    assert store.load("home-battery") is None
    assert "expired_at_restart" in incidents.read_text(encoding="utf-8")
    assert "commitment_recovery_rejected" in incidents.read_text(encoding="utf-8")


def test_capability_loss_rejects_restart_commitment(tmp_path) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    store.save(_commitment())
    source = _at(BASE + timedelta(minutes=15))
    unavailable = replace(
        source,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            capabilities=tuple(
                replace(
                    item,
                    availability=CapabilityAvailability.UNAVAILABLE,
                )
                for item in source.capability_snapshot_set.capabilities
            ),
        ),
    )

    restored = _restore_active_plan_commitments(unavailable, store)

    assert restored.active_plan_commitments == ()
    assert store.load("home-battery") is None
    assert "commitment_recovery_rejected" in incidents.read_text(encoding="utf-8")


def test_corrupt_commitment_file_creates_deduplicated_incident(tmp_path) -> None:
    path = tmp_path / "commitment.json"
    incidents = tmp_path / "incidents.jsonl"
    path.write_text("{broken", encoding="utf-8")
    store = ActivePlanCommitmentStore(path, incident_path=incidents)

    assert store.load("home-battery") is None
    assert store.load("home-battery") is None

    rows = incidents.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert "commitment_store_unreadable" in rows[0]
