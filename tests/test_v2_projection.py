from dataclasses import replace
from datetime import UTC, datetime, timedelta

from picot.v2.contracts import (
    CurrentStorageState,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project


def test_v2_projection_exposes_nine_cards_without_new_decisions() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    )
    projection = project(run)

    assert len(projection.cards) == 9
    assert projection.projection_ms >= 0.0
    assert [card.entity_id for card in projection.cards] == [
        "sensor.picot_v2_pipeline_01_planning_input",
        "sensor.picot_v2_pipeline_02_opportunity_engine",
        "sensor.picot_v2_pipeline_03_candidate_engine",
        "sensor.picot_v2_pipeline_04_evaluation_engine",
        "sensor.picot_v2_pipeline_05_execution_plan_builder",
        "sensor.picot_v2_pipeline_06_execution_engine",
        "sensor.picot_v2_pipeline_07_execution_primitive",
        "sensor.picot_v2_pipeline_08_device_adapter",
        "sensor.picot_v2_pipeline_09_vendor_result",
    ]
    assert all(card.attributes["run_id"] == run.planning_input.run_id for card in projection.cards)
    assert all(
        card.attributes["snapshot_id"] == run.planning_input.snapshot_id
        for card in projection.cards
    )
    assert projection.cards[7].state == "not_invoked"
    assert projection.cards[8].state == "not_dispatched"


def test_planning_input_card_projects_canonical_current_storage_state() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    storage_state = CurrentStorageState(
        storage_state_id="storage-state-home-battery",
        execution_scope_id="home-battery",
        capability_id="storage-capability-home-battery",
        current_soc=0.40,
        usable_capacity_wh=8160.0,
        measured_at=datetime(2026, 8, 14, 9, 59, 55, tzinfo=UTC),
        confidence=0.0,
        evidence_ids=("evidence-zendure-live",),
    )
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            current_storage_states=(storage_state,),
        )
    )

    planning_input_card = project(run).cards[0]

    assert planning_input_card.attributes["current_storage_state_count"] == 1
    assert planning_input_card.attributes["current_storage_states"] == [
        {
            "storage_state_id": "storage-state-home-battery",
            "execution_scope_id": "home-battery",
            "capability_id": "storage-capability-home-battery",
            "current_soc": 0.40,
            "usable_capacity_wh": 8160.0,
            "current_stored_energy_wh": 3264.0,
            "measured_at": "2026-08-14T09:59:55+00:00",
            "confidence": 0.0,
            "evidence_ids": ["evidence-zendure-live"],
        }
    ]


def test_planning_input_card_projects_compact_pv_energy_summary() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    starts_at = captured_at + timedelta(minutes=30)
    intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-interval-1",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            pv_energy_wh=1200.0,
            evidence_type="FORECAST",
            confidence=0.90,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-1",),
            conversion_method_version="solcast:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-interval-2",
            starts_at=starts_at + timedelta(minutes=30),
            ends_at=starts_at + timedelta(minutes=60),
            pv_energy_wh=1350.0,
            evidence_type="FORECAST",
            confidence=0.85,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-2",),
            conversion_method_version="solcast:v1",
        ),
    )
    timeline = PVEnergyTimeline(
        timeline_id="pv-timeline-1",
        run_id=bootstrap.run_id,
        snapshot_id=bootstrap.snapshot_id,
        intervals=intervals,
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            pv_energy_timeline=timeline,
        )
    )

    planning_input_card = project(run).cards[0]

    assert planning_input_card.attributes["pv_energy_timeline_available"] is True
    assert planning_input_card.attributes["pv_energy_interval_count"] == 2
    assert planning_input_card.attributes["pv_energy_total_wh"] == 2550.0
    assert (
        planning_input_card.attributes["pv_energy_starts_at"]
        == "2026-08-14T10:30:00+00:00"
    )
    assert (
        planning_input_card.attributes["pv_energy_ends_at"]
        == "2026-08-14T11:30:00+00:00"
    )
    assert planning_input_card.attributes["pv_energy_confidence_min"] == 0.85
    assert planning_input_card.attributes["pv_energy_confidence_average"] == 0.875
    assert planning_input_card.attributes["pv_energy_intervals"] == [
        {
            "interval_id": "pv-interval-1",
            "starts_at": "2026-08-14T10:30:00+00:00",
            "ends_at": "2026-08-14T11:00:00+00:00",
            "pv_energy_wh": 1200.0,
            "evidence_type": "FORECAST",
            "confidence": 0.90,
            "actual_evidence_ids": [],
            "forecast_evidence_ids": ["solcast-1"],
            "conversion_method_version": "solcast:v1",
        },
        {
            "interval_id": "pv-interval-2",
            "starts_at": "2026-08-14T11:00:00+00:00",
            "ends_at": "2026-08-14T11:30:00+00:00",
            "pv_energy_wh": 1350.0,
            "evidence_type": "FORECAST",
            "confidence": 0.85,
            "actual_evidence_ids": [],
            "forecast_evidence_ids": ["solcast-2"],
            "conversion_method_version": "solcast:v1",
        },
    ]
