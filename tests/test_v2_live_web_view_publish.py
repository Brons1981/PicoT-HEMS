import json
from datetime import UTC, datetime, timedelta

import pytest

import picot.v2.live_runtime as live_runtime
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import Card
from picot.v2.web_ui import WebViewStore


def test_completed_live_pipeline_run_publishes_latest_web_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    snapshot = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    bundle = PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at + timedelta(milliseconds=2),
    )
    price_config = PriceOpportunityConfig(
        low_price_margin_eur_per_kwh=0.02,
        high_price_margin_eur_per_kwh=0.02,
        config_version="test:v1",
    )
    published_cards: list[Card] = []

    class FakeSink:
        def __init__(self, token: str) -> None:
            assert token == "test-token"

        def publish(self, card: Card) -> None:
            published_cards.append(card)

    monkeypatch.setattr(
        live_runtime,
        "HomeAssistantProjectionSink",
        FakeSink,
    )
    store = WebViewStore()

    live_runtime._execute_planning_bundle(
        token="test-token",
        price_config=price_config,
        bundle=bundle,
        web_view_store=store,
    )

    latest_json = store.latest_json()
    assert latest_json is not None
    view = json.loads(latest_json)

    assert len(published_cards) == 10
    assert view["observer_only"] is True
    assert view["run_id"] == snapshot.run_id
    assert view["snapshot_id"] == snapshot.snapshot_id
    assert len(view["pipeline"]) == 9
    assert [item["stage"] for item in view["pipeline"]] == list(
        range(1, 10)
    )
