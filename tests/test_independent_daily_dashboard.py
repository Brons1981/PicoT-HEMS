from __future__ import annotations

from dataclasses import replace

import pytest
from test_independent_daily_observer_runtime import _runtime
from test_independent_daily_reference_adapter import _snapshot

from picot.v2.independent_daily_dashboard import (
    build_daily_observer_dashboard_view,
)
from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore


def test_completed_daily_outcome_projects_comparable_best_observations(
    tmp_path,
) -> None:
    outcome = _runtime(tmp_path).observe(_snapshot(maximum_soc=0.7))

    view = build_daily_observer_dashboard_view(outcome)

    assert view["available"] is True
    assert view["snapshot_id"] == outcome.snapshot_id
    assert view["observer_only"] is True
    assert view["selection_permitted"] is False
    assert view["commitment_permitted"] is False
    candidates = view["candidates"]
    assert isinstance(candidates, list)
    best = [item for item in candidates if item["best_observation"]]
    assert [item["candidate_id"] for item in best] == view[
        "best_observation_ids"
    ]
    assert all(item["scenarios"] for item in best)
    assert all(item["intent_intervals"] for item in best)


def test_blocked_daily_outcome_remains_visible_without_candidate_claims(
    tmp_path,
) -> None:
    snapshot = replace(_snapshot(maximum_soc=0.7), price_points=())
    outcome = _runtime(tmp_path).observe(snapshot)

    view = build_daily_observer_dashboard_view(outcome)

    assert view["available"] is False
    assert view["status"] == "blocked"
    assert view["reason"] == "daily_tariff_prices_missing"
    assert view["best_observation_ids"] == []
    assert view["candidates"] == []


def test_web_store_overlays_daily_result_and_keeps_it_on_canonical_publish() -> None:
    store = WebViewStore()
    comparison = {
        "observer_only": True,
        "selection_permitted": False,
        "commitment_permitted": False,
        "snapshot_id": "snapshot-observer",
        "candidates": [],
    }

    store.publish({"snapshot_id": "snapshot-canonical-1"})
    store.publish_daily_observer_comparison(comparison)
    first = store.latest_json()
    assert first is not None
    assert "snapshot-observer" in first

    store.publish({"snapshot_id": "snapshot-canonical-2"})
    second = store.latest_json()
    assert second is not None
    assert "snapshot-observer" in second


def test_web_store_rejects_daily_result_with_control_authority() -> None:
    store = WebViewStore()

    with pytest.raises(ValueError, match="must remain passive"):
        store.publish_daily_observer_comparison({
            "observer_only": True,
            "selection_permitted": True,
            "commitment_permitted": False,
        })


def test_dashboard_visually_separates_daily_observer_from_canonical_plan() -> None:
    assert 'id="daily-observer-comparison"' in DASHBOARD_HTML
    assert "renderDailyObserverComparison" in DASHBOARD_HTML
    assert "daily-reference" in DASHBOARD_HTML
    assert "#a855f7" in DASHBOARD_HTML
    assert "Exact dezelfde Planning Input" in DASHBOARD_HTML
    assert "vorige snapshot" in DASHBOARD_HTML
    assert "Fysieke batterijlimieten ontbreken" in DASHBOARD_HTML
    assert "Wacht op volledige Nordpool-prijzen" in DASHBOARD_HTML
