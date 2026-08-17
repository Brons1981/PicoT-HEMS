from dataclasses import replace
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
from picot.v2.web_ui import _build_plan_explanation

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
    assert outcome.pv_storage_contribution_wh == pytest.approx(200.0)
    assert outcome.grid_storage_contribution_wh == pytest.approx(0.0)
    assert outcome.storage_energy_at_window_end_wh == pytest.approx(1200.0)
    assert outcome.storage_energy_at_requirement_wh == pytest.approx(1200.0)
    assert outcome.requirement_satisfied is True


def test_projection_exposes_timed_candidate_window() -> None:
    projection = project(CanonicalPipeline().run(planning_input=_snapshot()))
    candidate_card = projection.cards[2]

    assert candidate_card.attributes["timed_storage_candidate_count"] == 1
    timed = candidate_card.attributes["timed_storage_candidates"][0]
    assert timed["family"] == "pv_charge_only"
    assert timed["primitive"] == "balance_charge_only"
    assert timed["charge_source_policy"] == "pv_only"
    assert timed["starts_at"] == BASE.isoformat()
    assert timed["ends_at"] == WINDOW_END.isoformat()
    assert timed["pv_storage_contribution_kwh"] == pytest.approx(0.2)
    assert timed["grid_storage_contribution_kwh"] == pytest.approx(0.0)
    assert timed["storage_energy_at_requirement_kwh"] == pytest.approx(1.2)
    assert timed["confidence"] == pytest.approx(0.7)


def test_evaluation_selects_requirement_satisfying_path_deterministically() -> None:
    first = CanonicalPipeline().run(planning_input=_snapshot())
    second = CanonicalPipeline().run(planning_input=_snapshot())

    delegated = next(
        candidate
        for candidate in first.candidate_set.candidates
        if candidate.family == "pv_charge_only"
    )
    assert first.evaluation.status == "winner_selected"
    assert first.evaluation.evaluated_candidate_ids == tuple(
        candidate.candidate_id for candidate in first.candidate_set.candidates
    )
    assert first.evaluation.winning_candidate_id == delegated.candidate_id
    assert first.evaluation.winning_energy_path_id == delegated.energy_path_id
    assert first.evaluation.decisive_step == (
        "hard_constraint:storage_requirement_satisfied"
    )
    assert first.evaluation.reason == (
        "pv_charge_only satisfies the storage requirement using PV-only energy"
    )
    assert first.evaluation == second.evaluation


def test_winning_delegated_path_becomes_unchanged_observer_plan() -> None:
    run = CanonicalPipeline().run(planning_input=_snapshot())
    winning_path = next(
        path
        for path in run.candidate_set.energy_paths
        if path.path_id == run.evaluation.winning_energy_path_id
    )

    assert run.execution_plan_set.winning_energy_path_id == winning_path.path_id
    assert len(run.execution_plan_set.plans) == 1
    plan = run.execution_plan_set.plans[0]
    assert plan.execution_scope_id == "home-battery"
    assert plan.observer_only is True
    assert plan.winning_candidate_id == run.evaluation.winning_candidate_id
    assert plan.winning_energy_path_id == winning_path.path_id
    assert len(plan.segments) == len(winning_path.segments)
    for plan_segment, path_segment in zip(
        plan.segments,
        winning_path.segments,
        strict=True,
    ):
        assert plan_segment.source_path_segment_id == path_segment.segment_id
        assert plan_segment.starts_at == path_segment.starts_at
        assert plan_segment.ends_at == path_segment.ends_at
        assert plan_segment.primitive == path_segment.primitive
        assert plan_segment.capability_id == path_segment.capability_id
        assert plan_segment.requested_power_w is None
        assert (
            plan_segment.charge_source_policy
            == path_segment.charge_source_policy
        )

    assert run.execution_record.status == "observer_only_plan_ready"
    assert run.primitive_boundary.request_id is None
    assert run.primitive_boundary.status == "not_emitted"
    assert run.adapter_boundary.translation_id is None
    assert run.adapter_boundary.status == "not_invoked"
    assert run.vendor_result.command_id is None
    assert run.vendor_result.status == "not_dispatched"


def test_projection_explains_winner_and_observer_only_plan() -> None:
    projection = project(CanonicalPipeline().run(planning_input=_snapshot()))
    evaluation_card = projection.cards[3]
    plan_card = projection.cards[4]

    assert evaluation_card.state == "winner_selected"
    assert evaluation_card.attributes["decisive_step"] == (
        "hard_constraint:storage_requirement_satisfied"
    )
    assert evaluation_card.attributes["winning_family"] == "pv_charge_only"
    assert evaluation_card.attributes["reason"] == (
        "pv_charge_only satisfies the storage requirement using PV-only energy"
    )
    assert plan_card.state == "observer_only"
    assert plan_card.attributes["plan_count"] == 1
    planned = plan_card.attributes["plans"][0]
    assert planned["execution_scope_id"] == "home-battery"
    assert planned["observer_only"] is True
    assert planned["segment_count"] == 1
    assert planned["segments"][0]["primitive"] == "balance_charge_only"
    assert planned["segments"][0]["charge_source_policy"] == "pv_only"
    assert planned["segments"][0]["requested_power_w"] is None


def test_partial_pv_progress_cannot_be_released_as_a_winner() -> None:
    source = _snapshot()
    first_pv = source.pv_energy_timeline.intervals[0]
    snapshot = replace(
        source,
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=(
                replace(first_pv, pv_energy_wh=300.0),
                source.pv_energy_timeline.intervals[1],
            ),
        ),
    )

    run = CanonicalPipeline().run(planning_input=snapshot)

    outcome = run.outcomes.outcomes[0]
    assert outcome.requirement_satisfied is False
    assert outcome.pv_storage_contribution_wh == pytest.approx(100.0)
    assert run.evaluation.status == "fallback_active"
    assert run.evaluation.winning_candidate_id != outcome.candidate_id
    assert run.evaluation.decisive_step == "fallback:no_actionable_candidate"
    assert run.execution_record.status != "observer_only_plan_ready"
    explanation = _build_plan_explanation(run)
    partial = next(
        plan for plan in explanation["plans"] if plan["family"] == "pv_charge_only"
    )
    assert partial["selected"] is False
