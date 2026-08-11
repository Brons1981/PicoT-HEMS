from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from picot.addon import price_runtime_v2, runtime
from picot.addon.canonical_price_pipeline import run_canonical_price_pipeline
from picot.addon.price_runtime_v2 import _price_entry_observation
from picot.domain.candidate import CandidateFamily
from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.opportunity import OpportunityKind

BASE = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _forecast(values: tuple[float, ...]) -> ForecastSeries:
    points = tuple(
        ForecastPoint(
            starts_at=BASE + timedelta(minutes=15 * index),
            ends_at=BASE + timedelta(minutes=15 * (index + 1)),
            value=value,
            confidence=1.0,
        )
        for index, value in enumerate(values)
    )
    return ForecastSeries(
        forecast_id="price-entry-observation-test",
        kind=ForecastKind.ENERGY_PRICE,
        source="test",
        created_at=BASE - timedelta(minutes=5),
        expires_at=points[-1].ends_at,
        unit="EUR/kWh",
        points=points,
    )


def test_canonical_pipeline_emits_opportunities_then_cost_first_exclusions() -> None:
    forecast = _forecast((0.20, 0.158, 0.164, 0.143, 0.134, 0.131, 0.127, 0.18))

    result = run_canonical_price_pipeline(
        forecast,
        evaluated_at=BASE,
        price_margin_eur_per_kwh=0.04,
    )

    assert result.opportunities.snapshot_id == result.snapshot.snapshot_id
    assert any(
        item.kind is OpportunityKind.LOWEST_PRICE_WINDOW
        for item in result.opportunities.opportunities
    )
    assert any(
        item.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
        for item in result.opportunities.opportunities
    )
    assert result.candidates.snapshot_id == result.snapshot.snapshot_id
    assert len(result.candidates.candidates) == 1
    assert result.candidates.candidates[0].family is CandidateFamily.RESERVE_FIRST
    assert result.candidates.exclusions
    assert all(
        exclusion.family is CandidateFamily.COST_FIRST
        for exclusion in result.candidates.exclusions
    )


def test_observation_flags_lower_later_price_inside_canonical_opportunity() -> None:
    forecast = _forecast((0.20, 0.158, 0.164, 0.143, 0.134, 0.131, 0.127, 0.18))
    pipeline = run_canonical_price_pipeline(
        forecast,
        evaluated_at=BASE,
        price_margin_eur_per_kwh=0.04,
    )

    observation = _price_entry_observation(
        pipeline.opportunities,
        forecast,
        evaluated_at=BASE,
    )

    assert observation["price_entry_observation_only"] is True
    assert observation["price_entry_replan_input"] is False
    assert observation["price_entry_observation_status"] == "lower_later_price_exists"
    assert observation["price_entry_reference_price_eur_per_kwh"] == pytest.approx(0.158)
    assert observation["price_entry_best_later_price_eur_per_kwh"] == pytest.approx(0.127)
    assert observation["price_entry_best_later_saving_eur_per_kwh"] == pytest.approx(0.031)
    assert "not a best start" in str(observation["price_entry_limitation"])

    alternatives = observation["price_entry_alternatives"]
    assert isinstance(alternatives, list)
    plus_30 = next(item for item in alternatives if item["delay_minutes"] == 30)
    assert plus_30["price_eur_per_kwh"] == pytest.approx(0.143)
    assert plus_30["cheaper_than_entry"] is True


def test_runtime_does_not_query_target_or_arm_legacy_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forecast = _forecast((0.20, 0.158, 0.164, 0.143, 0.134, 0.131, 0.127, 0.18))
    requested_paths: list[str] = []

    def fake_request_json(path: str, token: str) -> dict[str, Any]:
        del token
        requested_paths.append(path)
        if path == "/api/states/sensor.price":
            return {"entity_id": "sensor.price", "attributes": {}}
        raise AssertionError(f"Unexpected Home Assistant read: {path}")

    monkeypatch.setattr(runtime, "_request_json", fake_request_json)
    monkeypatch.setattr(runtime, "_price_forecast", lambda state, now: forecast)

    event = price_runtime_v2.run_planner_once(
        {
            "price_entity": "sensor.price",
            "target_entity": "input_select.must_not_be_read",
            "price_opportunity_margin_eur_per_kwh": 0.04,
            "mode": "dry_run",
            "planner_interval_seconds": 60,
        },
        "token",
        now=BASE,
    )

    assert requested_paths == ["/api/states/sensor.price"]
    assert event["pipeline_stage_reached"] == "candidate_generation"
    assert event["control_change_allowed"] is False
    assert event["dispatch_status"] == "blocked_by_candidate_contract"
    assert event["candidate_exclusion_count"] > 0
    assert "window_starts_at" not in event
    assert "window_ends_at" not in event
    assert runtime._scheduled_boundary(event, now=BASE) is None
