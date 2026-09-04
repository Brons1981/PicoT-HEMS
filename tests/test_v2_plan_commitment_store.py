from datetime import UTC, datetime, timedelta

from picot.v2.plan_commitment_store import (
    ActivePlanCommitment,
    ActivePlanCommitmentStore,
    CommittedHouseholdLoadInterval,
    CommittedPlanSegment,
    CommittedStorageEnergyCheckpoint,
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
        pv_preservation_dates=(starts_at.date(),),
    )

    ActivePlanCommitmentStore(path).save(commitment)

    assert ActivePlanCommitmentStore(path).load("home-battery") == commitment


def test_mep_challenger_evidence_survives_store_restart(tmp_path) -> None:
    path = tmp_path / "commitments.json"
    starts_at = datetime(2026, 8, 27, 10, 30, tzinfo=UTC)
    commitment = ActivePlanCommitment(
        execution_scope_id="home-battery",
        plan_id="mep-plan:snapshot-before-boundary",
        plan_revision=1,
        primitive="balance_bidirectional",
        source_policy="pv_only",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        target_energy_wh=8160.0,
        selection_method_version="mep-active-plan-commitment:v1",
        planner_id="mep",
        schedule_id="mep-window-12:30-14:30",
        worst_case_financial_result_eur=1.33,
        average_charge_window_price_eur_per_kwh=0.134,
        minimum_confidence=0.19,
        reserve_respected_across_scenarios=True,
        target_held_across_scenarios=False,
        minimum_storage_energy_at_horizon_end_wh=6470.0,
        segments=(
            CommittedPlanSegment(
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                primitive="balance_bidirectional",
                source_policy="pv_only",
            ),
            CommittedPlanSegment(
                starts_at=starts_at + timedelta(hours=1),
                ends_at=starts_at + timedelta(hours=2),
                primitive="balance_discharge_only",
                source_policy=None,
            ),
        ),
        selection_reason="material_change:test",
        replaced_plan_id="mep-plan:previous",
        selected_at=starts_at - timedelta(minutes=5),
        household_load_intervals=(
            CommittedHouseholdLoadInterval(
                interval_id="load-baseline-1",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=15),
                expected_energy_wh=125.0,
                confidence=0.8,
                source_reference="history:baseline",
                method_version="household-load:v1",
            ),
        ),
        storage_energy_checkpoints=(
            CommittedStorageEnergyCheckpoint(
                at=starts_at + timedelta(minutes=15),
                lower_energy_wh=4000.0,
                central_energy_wh=4200.0,
                upper_energy_wh=4400.0,
            ),
        ),
        candidate_family="mixed_schedule",
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
