import json
from dataclasses import replace
from datetime import timedelta

from test_independent_daily_reference_adapter import _conversion, _snapshot

from picot.planner.market_daily_planner import MarketDailyPlanner
from picot.v2.market_daily_dashboard import (
    build_market_daily_dashboard_view,
    build_market_daily_runtime_view,
)
from picot.v2.market_daily_runtime import MarketDailyPlannerRuntime
from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore


def test_mep_dashboard_exposes_baseline_market_and_authority_separately() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.95)
    negative_start = snapshot.captured_at + timedelta(hours=2)
    priced = (
        replace(
            snapshot.price_points[0],
            point_id="before",
            ends_at=negative_start,
            value_eur_per_kwh=0.20,
        ),
        replace(
            snapshot.price_points[0],
            point_id="negative",
            starts_at=negative_start,
            ends_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=-0.05,
        ),
        replace(
            snapshot.price_points[0],
            point_id="after",
            starts_at=negative_start + timedelta(hours=2),
            value_eur_per_kwh=0.20,
        ),
    )
    plan = MarketDailyPlanner().plan(
        snapshot=replace(snapshot, price_points=priced),
        conversion_model=_conversion(),
    )

    view = build_market_daily_dashboard_view(plan)

    assert view["planner_id"] == "mep"
    assert view["planner_name"] == "Markt Etmaal Planner"
    assert view["selection_reason"] == plan.selection_reason
    assert view["selected_intent_schedule_id"] == (
        plan.selected_intent_schedule.schedule_id
    )
    assert view["snapshot_id"] == snapshot.snapshot_id
    assert view["frozen_baseline_observation_id"] == plan.baseline.observation_id
    assert view["winning_source"] == "market_route"
    assert view["dispatch_authority"] is False
    assert view["current_intent"] == "storage_export"
    assert view["current_interval_ends_at"] is not None
    assert view["route_count"] == 1
    assert view["admitted_route_count"] >= 1
    assert any(
        item["intent"] == "storage_export"
        for item in view["selected_intent_intervals"]
    )
    route = view["routes"][0]
    assert route["maximum_charge_input_kwh"] == 4.8
    assert route["reserved_storage_room_kwh"] == 4.8
    assert route["assessment_count"] >= 1
    assert route["admitted"] is True


def test_web_store_keeps_mep_separate_from_existing_planner_views() -> None:
    store = WebViewStore()
    store.publish({"snapshot_id": "snapshot", "canonical": "unchanged"})

    store.publish_market_daily_planner({
        "planner_id": "mep",
        "snapshot_id": "snapshot",
        "dispatch_authority": False,
    })

    latest_json = store.latest_json()
    assert latest_json is not None
    latest = json.loads(latest_json)
    assert latest["canonical"] == "unchanged"
    assert latest["market_daily_planner"]["planner_id"] == "mep"


def test_mep_runtime_dashboard_exposes_its_complete_baseline_plan() -> None:
    snapshot = _snapshot(maximum_soc=1.0, current_soc=0.51)
    outcome = MarketDailyPlannerRuntime(_conversion()).plan(snapshot)

    view = build_market_daily_runtime_view(outcome)

    baseline = view["baseline_plan"]
    winners = [
        item for item in baseline["candidates"] if item["best_observation"]
    ]
    assert baseline["captured_at"] == snapshot.captured_at.isoformat()
    assert baseline["simulation_horizon_start"] is not None
    assert baseline["simulation_horizon_end"] is not None
    assert winners
    assert winners[0]["intent_intervals"]


def test_dashboard_renders_mep_as_a_third_visually_distinct_planner() -> None:
    assert "MEP · Markt Etmaal Planner" in DASHBOARD_HTML
    assert "view.market_daily_planner" in DASHBOARD_HTML
    assert ".daily-comparison-card.market-daily" in DASHBOARD_HTML
    assert "selectedMepIntents" in DASHBOARD_HTML
    assert ".price-bar.mep-charge" in DASHBOARD_HTML
    assert ".price-bar.mep-export" in DASHBOARD_HTML
