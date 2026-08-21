from datetime import UTC, datetime, timedelta

from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
)


def test_active_commitment_survives_store_restart(tmp_path) -> None:
    path = tmp_path / "commitments.json"
    starts_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="plan-stable",
        plan_revision=3,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        target_energy_wh=8160.0,
    )

    ActivePlanCommitmentStore(path).save(commitment)

    assert ActivePlanCommitmentStore(path).load("home-battery") == commitment


def test_clearing_one_scope_preserves_another(tmp_path) -> None:
    path = tmp_path / "commitments.json"
    store = ActivePlanCommitmentStore(path)
    starts_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    first = ActivePlanCommitment(
        "battery-a", "plan-a", 1, "balance_bidirectional", "pv_only",
        starts_at, starts_at + timedelta(hours=1), 8160.0,
    )
    second = ActivePlanCommitment(
        "battery-b", "plan-b", 1, "balance_bidirectional", "pv_only",
        starts_at, starts_at + timedelta(hours=1), 8160.0,
    )
    store.save(first)
    store.save(second)

    store.clear("battery-a")

    assert store.load("battery-a") is None
    assert store.load("battery-b") == second


def test_clear_all_returns_removed_commitments_and_preserves_incident_audit(
    tmp_path,
) -> None:
    path = tmp_path / "commitments.json"
    incidents = tmp_path / "incidents.jsonl"
    store = ActivePlanCommitmentStore(path, incident_path=incidents)
    starts_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    commitment = ActivePlanCommitment(
        "battery-a",
        "plan-a",
        1,
        "balance_bidirectional",
        "pv_only",
        starts_at,
        starts_at + timedelta(hours=1),
        8160.0,
    )
    store.save(commitment)

    removed = store.clear_all()
    store.record_manual_reset(reset_id="planning-reset-1", removed=removed)

    assert removed == (commitment,)
    assert store.load("battery-a") is None
    audit = incidents.read_text(encoding="utf-8")
    assert "manual_planning_reset_requested" in audit
    assert "planning-reset-1" in audit
    assert "plan-a" in audit
