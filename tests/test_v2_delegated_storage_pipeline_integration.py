from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.capability_snapshot import (
    CapabilityAvailability,
    CapabilityHealth,
    CapabilityRole,
    CapabilitySnapshotSet,
    EnergyFlowDirection,
    LogicalCapabilitySnapshot,
)
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.contracts import (
    CurrentStorageState,
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PlanningInputSnapshot,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project

BASE = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
WINDOW_END = BASE + timedelta(hours=1)
HORIZON_END = BASE + timedelta(hours=2)
RUN_ID = "run-delegated-pipeline-test"
SNAPSHOT_ID = "snapshot-delegated-pipeline-test"
CAPABILITY_ID = "storage-capability-home-battery"


def _snapshot() -> PlanningInputSnapshot:
    capability = LogicalCapabilitySnapshot(
        capability_id=CAPABILITY_ID,
        execution_scope_id="home-battery",
        supported_primitives=(ExecutionPrimitive.BALANCE_CHARGE_ONLY,),
        availability=CapabilityAvailability.AVAILABLE,
        health=CapabilityHealth.HEALTHY,
        fresh_at=BASE,
        confidence=1.0,
        source_mapping_id="storage-mode-options:v1",
        adapter_contract_version="1",
        role=CapabilityRole.ENERGY_STORAGE,
        flow_directions=(EnergyFlowDirection.CHARGE,),
    )
    storage = CurrentStorageState(
        storage_state_id="storage-home",
        execution_scope_id="home-battery",
        capability_id=CAPABILITY_ID,
        current_soc=1000.0 / 1200.0,
        usable_capacity_wh=1200.0,
        measured_at=BASE,
        confidence=0.9,
        evidence_ids=("storage-evidence",),
    )
    pv_intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            pv_energy_wh=800.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-window-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-after",
            starts_at=WINDOW_END,
            ends_at=HORIZON_END,
            pv_energy_wh=0.0,
            evidence_type="FORECAST",
            confidence=0.8,
            actual_evidence_ids=(),
            forecast_evidence_ids=("pv-after-evidence",),
            conversion_method_version="forecast-energy:v1",
        ),
    )
    load_intervals = (
        HouseholdLoadForecastInterval(
            interval_id="load-window",
            starts_at=BASE,
            ends_at=WINDOW_END,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-window-evidence",
            method_version="test-load:v1",
        ),
        HouseholdLoadForecastInterval(
            interval_id="load-after",
            starts_at=WINDOW_END,
            ends_at=HORIZON_END,
            expected_energy_wh=200.0,
            confidence=0.7,
            source_reference="load-after-evidence",
            method_version="test-load:v1",
        ),
    )
    return PlanningInputSnapshot(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        captured_at=BASE,
        picot_version="test",
        architecture_baseline_commit="test",
        pipeline_contract_version=1,
        strategy_id="strategy:test",
        horizon_end=HORIZON_END,
        current_storage_states=(storage,),
        pv_energy_timeline=PVEnergyTimeline(
            timeline_id="pv-timeline",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=pv_intervals,
        ),
        household_load_forecast=HouseholdLoadForecast(
            forecast_id="load-forecast",
            run_id=RUN_ID,
            snapshot_id=SNAPSHOT_ID,
            intervals=load_intervals,
            fallback_active=False,
            fallback_reason=None,
        ),
        capability_snapshot_set=CapabilitySnapshotSet(
            snapshot_id=SNAPSHOT_ID,
            mapping_version=1,
            captured_at=BASE,
            capabilities=(capability,),
        ),
    )


def test_canonical_pipeline_exposes_baseline_timed_candidate_and_outcome() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert [candidate.family for candidate in run.candidate_set.candidates] == [
        "reserve_first",
        "pv_charge_only",
    ]
    assert [path.family for path in run.candidate_set.energy_paths] == [
        "reserve_first",
        "pv_charge_only",
    ]
    assert len(run.outcomes.outcomes) == 1
    outcome = run.outcomes.outcomes[0]
    assert outcome.pv_storage_contribution_wh == pytest.approx(400.0)
    assert outcome.grid_storage_contribution_wh == pytest.approx(0.0)
    assert outcome.storage_energy_at_window_end_wh == pytest.approx(1400.0)
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.requirement_satisfied is True


def test_uncompared_alternatives_produce_no_winner_plan_or_dispatch() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())

    assert run.evaluation.status == "not_compared"
    assert run.evaluation.winning_candidate_id is None
    assert run.evaluation.winning_energy_path_id is None
    assert run.evaluation.reason == "candidate_outcomes_not_yet_comparable"
    assert run.execution_plan_set.winning_energy_path_id is None
    assert run.execution_plan_set.plan_ids == ()
    assert run.execution_record.status == "no_evaluated_winner"
    assert run.primitive_boundary.request_id is None
    assert run.adapter_boundary.translation_id is None
    assert run.vendor_result.command_id is None


def test_projection_exposes_timed_window_and_explicit_evaluation_block() -> None:
    projection = project(CanonicalPipeline().run(planning_input=_snapshot()))
    candidate_card = projection.cards[2]
    evaluation_card = projection.cards[3]
    plan_card = projection.cards[4]

    assert candidate_card.attributes["timed_storage_candidate_count"] == 1
    timed = candidate_card.attributes["timed_storage_candidates"][0]
    assert timed["family"] == "pv_charge_only"
    assert timed["primitive"] == "balance_charge_only"
    assert timed["charge_source_policy"] == "pv_only"
    assert timed["starts_at"] == BASE.isoformat()
    assert timed["ends_at"] == WINDOW_END.isoformat()
    assert timed["pv_storage_contribution_kwh"] == pytest.approx(0.4)
    assert timed["grid_storage_contribution_kwh"] == pytest.approx(0.0)
    assert timed["storage_energy_at_requirement_kwh"] == pytest.approx(1.2)
    assert timed["confidence"] == pytest.approx(0.7)
    assert evaluation_card.state == "not_compared"
    assert evaluation_card.attributes["winning_candidate_id"] is None
    assert evaluation_card.attributes["reason"] == (
        "candidate_outcomes_not_yet_comparable"
    )
    assert plan_card.state == "blocked"
    assert plan_card.attributes["plan_count"] == 0
