from datetime import UTC, datetime, timedelta

import pytest

from picot.v2 import ARCHITECTURE_BASELINE_COMMIT, PIPELINE_CONTRACT_VERSION, __version__
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint
from picot.v2.opportunity_engine import LOWEST_PRICE_WINDOW, OpportunityEngine, PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project

BASE = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


def point(index: int, value: float, confidence: float = 1.0) -> PriceForecastPoint:
    start = BASE + timedelta(hours=index)
    return PriceForecastPoint(
        point_id=f"p{index}",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        value_eur_per_kwh=value,
        confidence=confidence,
        evidence_id="forecast-1",
    )


def snapshot(points: tuple[PriceForecastPoint, ...]) -> PlanningInputSnapshot:
    return PlanningInputSnapshot(
        run_id="run-1",
        snapshot_id="snapshot-1",
        captured_at=BASE,
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:test",
        horizon_end=BASE + timedelta(hours=8),
        price_points=points,
    )


def config() -> PriceOpportunityConfig:
    return PriceOpportunityConfig(0.02, 0.0, "price-test-v1")


def test_missing_inputs_block_without_hidden_defaults() -> None:
    result = OpportunityEngine().detect(snapshot(()), price_config=config())
    assert result.detection_status == "blocked"
    assert result.detection_reason == "price_points_missing"

    result = OpportunityEngine().detect(snapshot((point(0, 0.2),)), price_config=None)
    assert result.detection_status == "blocked"
    assert result.detection_reason == "price_detector_config_missing"


def test_low_window_bridge_is_explicit_and_replayable() -> None:
    source = snapshot(
        (
            point(0, 0.10, 0.95),
            point(1, 0.14, 0.80),
            point(2, 0.10, 0.90),
            point(3, 0.30),
        )
    )
    first = OpportunityEngine().detect(source, price_config=config())
    second = OpportunityEngine().detect(source, price_config=config())
    low = tuple(item for item in first.opportunities if item.kind == LOWEST_PRICE_WINDOW)[0]

    assert first == second
    assert low.starts_at == BASE
    assert low.ends_at == BASE + timedelta(hours=3)
    assert low.metrics.boundary_eur_per_kwh == pytest.approx(0.12)
    assert low.metrics.average_price_eur_per_kwh == pytest.approx(0.11333333333333333)
    assert low.metrics.source_interval_count == 3
    assert low.metrics.bridged_interval_count == 1
    assert low.confidence == pytest.approx(0.80)
    assert low.evidence[0].point_ids == ("p0", "p1", "p2")


def test_pipeline_and_projection_use_same_opportunity_set() -> None:
    source = snapshot((point(0, 0.10), point(1, 0.12), point(2, 0.30)))
    run = CanonicalPipeline().run(
        planning_input=source,
        price_opportunity_config=config(),
    )
    card = project(run).cards[1]

    assert run.opportunities.detection_status == "ready"
    assert card.state == run.opportunities.detection_status
    assert card.attributes["output_reference"] == run.opportunities.opportunity_set_id
    assert card.attributes["opportunity_count"] == len(run.opportunities.opportunities)
    assert card.attributes["observer_only"] is True
