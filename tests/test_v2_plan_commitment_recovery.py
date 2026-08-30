from dataclasses import replace
from datetime import timedelta

import pytest
from test_v2_delegated_storage_pipeline_integration import BASE, _snapshot

from picot.domain.capability_snapshot import CapabilityAvailability
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.live_runtime import _restore_active_plan_commitments
from picot.v2.plan_commitment_store import (
    DEFECTIVE_COMMITMENT_METHOD_VERSION,
    EARLIER_COMMITMENT_METHOD_VERSION,
    LEGACY_COMMITMENT_METHOD_VERSION,
    PREVIOUS_COMMITMENT_METHOD_VERSION,
    TIMING_PREVIOUS_COMMITMENT_METHOD_VERSION,
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedPlanSegment,
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


def test_active_dev202_commitment_is_cleared_for_corrective_replan(
    tmp_path,
) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    active = replace(
        _commitment(),
        starts_at=BASE,
        ends_at=BASE + timedelta(days=1),
        selection_method_version=DEFECTIVE_COMMITMENT_METHOD_VERSION,
    )
    store.save(active)

    restored = _restore_active_plan_commitments(
        _at(BASE + timedelta(minutes=15)),
        store,
    )

    assert restored.active_plan_commitments == ()
    assert store.load("home-battery") is None
    assert "defective_commitment_requires_replan" in (
        incidents.read_text(encoding="utf-8")
    )


def test_balance_phase_with_previous_timing_is_cleared_for_replan(
    tmp_path,
) -> None:
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(
        tmp_path / "commitment.json",
        incident_path=incidents,
    )
    previous = replace(
        _commitment(),
        primitive="balance_discharge_only",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=4),
        selection_method_version=TIMING_PREVIOUS_COMMITMENT_METHOD_VERSION,
        segments=(
            CommittedPlanSegment(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=1),
                primitive="balance_discharge_only",
                source_policy=None,
            ),
            CommittedPlanSegment(
                starts_at=BASE + timedelta(hours=1),
                ends_at=BASE + timedelta(hours=2),
                primitive="charge_at_power",
                source_policy="pv_preferred_grid_allowed",
            ),
        ),
    )
    store.save(previous)

    restored = _restore_active_plan_commitments(
        _at(BASE + timedelta(minutes=15)),
        store,
    )

    assert restored.active_plan_commitments == ()
    assert "superseded_charge_timing_requires_replan" in (
        incidents.read_text(encoding="utf-8")
    )


def test_explicit_phase_with_previous_timing_remains_active(tmp_path) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    previous = replace(
        _commitment(),
        primitive="charge_at_power",
        source_policy="pv_preferred_grid_allowed",
        starts_at=BASE,
        ends_at=BASE + timedelta(hours=2),
        selection_method_version=TIMING_PREVIOUS_COMMITMENT_METHOD_VERSION,
        segments=(
            CommittedPlanSegment(
                starts_at=BASE,
                ends_at=BASE + timedelta(hours=1),
                primitive="charge_at_power",
                source_policy="pv_preferred_grid_allowed",
            ),
        ),
    )
    store.save(previous)

    source = _at(BASE + timedelta(minutes=15))
    capable = replace(
        source,
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            capabilities=tuple(
                replace(
                    item,
                    supported_primitives=(
                        *item.supported_primitives,
                        ExecutionPrimitive.CHARGE_AT_POWER,
                    ),
                )
                for item in source.capability_snapshot_set.capabilities
            ),
        ),
    )
    restored = _restore_active_plan_commitments(capable, store)

    assert restored.active_plan_commitments == (previous,)


@pytest.mark.parametrize(
    "selection_method_version",
    (PREVIOUS_COMMITMENT_METHOD_VERSION, EARLIER_COMMITMENT_METHOD_VERSION),
)
def test_active_pre_subwindow_commitment_remains_fixed_until_phase_end(
    tmp_path,
    selection_method_version,
) -> None:
    store = ActivePlanCommitmentStore(tmp_path / "commitment.json")
    active = replace(
        _commitment(),
        selection_method_version=selection_method_version,
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
