import json
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.error import HTTPError

import pytest

import picot.v2.live_runtime as live_runtime
from picot.v2.independent_daily_observer_runtime import (
    IndependentDailyObserverWorker,
)
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
    submitted_snapshot_ids: list[str] = []
    store = WebViewStore()

    class FakeDailyObserverWorker:
        def submit(self, submitted_snapshot) -> None:
            submitted_snapshot_ids.append(submitted_snapshot.snapshot_id)

    class FakeSink:
        def __init__(self, token: str) -> None:
            assert token == "test-token"

        def publish(self, card: Card) -> None:
            assert store.latest_json() is not None
            published_cards.append(card)

    monkeypatch.setattr(
        live_runtime,
        "HomeAssistantProjectionSink",
        FakeSink,
    )
    live_runtime._execute_planning_bundle(
        token="test-token",
        price_config=price_config,
        bundle=bundle,
        web_view_store=store,
        power_history_read_ms=12.5,
        independent_daily_observer_worker=cast(
            IndependentDailyObserverWorker,
            FakeDailyObserverWorker(),
        ),
    )

    latest_json = store.latest_json()
    assert latest_json is not None
    view = json.loads(latest_json)

    assert len(published_cards) == 10
    assert view["observer_only"] is True
    assert view["run_id"] == snapshot.run_id
    assert view["snapshot_id"] == snapshot.snapshot_id
    assert submitted_snapshot_ids == [snapshot.snapshot_id]
    assert len(view["pipeline"]) == 9
    assert [item["stage"] for item in view["pipeline"]] == list(
        range(1, 10)
    )
    performance = next(
        card for card in published_cards
        if card.entity_id == "sensor.picot_v2_diagnostic_performance"
    )
    assert performance.attributes["power_history_read_ms"] == 12.5
    assert performance.attributes["web_view_build_ms"] >= 0.0
    assert performance.attributes["web_view_publish_ms"] >= 0.0


def test_temporary_home_assistant_publish_failure_does_not_stop_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    snapshot = CanonicalPipeline().run(captured_at=captured_at).planning_input
    bundle = PlanningInputBundle(
        snapshot=snapshot,
        evidence=(),
        facts=(),
        assembly_started_at=captured_at,
        assembly_finished_at=captured_at + timedelta(milliseconds=2),
    )
    attempts: list[str] = []
    store = WebViewStore()

    class FailingSink:
        def __init__(self, token: str) -> None:
            assert token == "test-token"

        def publish(self, card: Card) -> None:
            attempts.append(card.entity_id)
            raise HTTPError(
                url="http://supervisor/core/api/states/test",
                code=502,
                msg="Bad Gateway",
                hdrs=None,
                fp=None,
            )

    monkeypatch.setattr(live_runtime, "HomeAssistantProjectionSink", FailingSink)

    live_runtime._execute_planning_bundle(
        token="test-token",
        price_config=PriceOpportunityConfig(
            low_price_margin_eur_per_kwh=0.02,
            high_price_margin_eur_per_kwh=0.02,
            config_version="test:v1",
        ),
        bundle=bundle,
        web_view_store=store,
    )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    publish_error = next(
        event
        for event in events
        if event["event"] == "picot_v2_ha_projection_publish_error"
    )
    ready = next(
        event
        for event in events
        if event["event"] == "picot_v2_planning_input_ready"
    )
    assert attempts == ["sensor.picot_v2_pipeline_01_planning_input"]
    assert publish_error["run_id"] == snapshot.run_id
    assert publish_error["error"] == "HTTP Error 502: Bad Gateway"
    assert ready["ha_publish_status"] == "retry_next_poll"
    assert store.latest_json() is not None
