"""Plan notifications and optional settlement observe an already published plan."""
import json

import pytest
from test_daily_main_active_pipeline import setup

from picot.v2 import live_runtime
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.power_history import PowerHistorySnapshot
from picot.v2.soc_projection_cache import SOCProjectionCache
from picot.v2.web_ui import WebViewStore


@pytest.mark.parametrize("failed_observer", [None, "notification", "financial"])
def test_current_plan_and_soc_are_published_before_optional_observers(
    tmp_path, monkeypatch, failed_observer,
):
    commitments, pipeline, recover = setup(tmp_path, monkeypatch)
    snapshot = recover()
    cache_path = tmp_path / "soc.json"
    web = WebViewStore(soc_cache=SOCProjectionCache(cache_path))
    events = []
    observed = {}

    def capture(name):
        events.append(name)
        observed[name] = (
            json.loads(web.latest_json()) if web.latest_json() else None,
            json.loads(cache_path.read_text()) if cache_path.exists() else None,
        )

    class Notifier:
        def update(self, *args, **kwargs):
            capture("notification")
            if failed_observer == "notification":
                raise OSError("notification unavailable")

    class Ledger:
        def update(self, *args, **kwargs):
            capture("financial")
            # A newer display update arriving during settlement must survive.
            if web.latest_json():
                newer = json.loads(web.latest_json())
                newer["concurrent_display_marker"] = "preserve-me"
                web.publish(newer)
            if failed_observer == "financial":
                raise OSError("settlement unavailable")
            return {"observer_only": True, "selection_permitted": False,
                    "commitment_permitted": False, "test_result": "settled"}

    monkeypatch.setattr(live_runtime, "observe_planning_run",
                        lambda *args: capture("health"))
    monkeypatch.setattr(live_runtime.HomeAssistantProjectionSink, "publish",
                        lambda *args: None)
    live_runtime._execute_planning_bundle(
        token="test-token", canonical_pipeline=pipeline,
        price_config=PriceOpportunityConfig(0.02, 0.02, "test"),
        bundle=PlanningInputBundle(snapshot, (), (), snapshot.captured_at, snapshot.captured_at),
        web_view_store=web, health_notifier=object(),
        planning_fallback_notifier=Notifier(), financial_result_ledger=Ledger(),
        power_history=PowerHistorySnapshot(
            starts_at=snapshot.captured_at, ends_at=snapshot.captured_at,
            status="available", error=None, series=(),
        ),
    )
    assert events == ["health", "notification", "financial"]
    assert observed["health"] == (None, None)  # Health alerts keep their early ordering.
    active = commitments.load_active_daily_main_plan("battery")
    for name in ("notification", "financial"):
        view, cached = observed[name]
        assert view is not None, f"{name} ran before dashboard publication"
        status = view["planning_status"]
        assert status["chosen_plan"]["plan_id"] == active.plan_id
        assert status["soc_timeline"]
        assert cached["identity"]["plan_id"] == active.plan_id
        assert cached["soc_timeline"] == status["soc_timeline"]
    latest = json.loads(web.latest_json())
    assert latest["concurrent_display_marker"] == "preserve-me"
    assert latest["planning_status"]["chosen_plan"]["plan_id"] == active.plan_id
    if failed_observer != "financial":
        assert latest["financial_results"]["test_result"] == "settled"
