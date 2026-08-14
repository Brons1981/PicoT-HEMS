from dataclasses import replace
from datetime import UTC, datetime

from picot.v2.contracts import CurrentStorageState
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
