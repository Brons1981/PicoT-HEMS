from datetime import datetime, timezone

from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project


def test_v2_projection_exposes_nine_cards_without_new_decisions() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
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
