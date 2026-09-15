"""Live observations must refresh independently of economic replanning."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from picot.v2.storage_mode_transition_history import StorageModeTransitionEvent
from picot.v2.web_ui import DASHBOARD_HTML, WebViewStore


def test_clock_transition_refreshes_view_without_replacing_plan() -> None:
    store = WebViewStore()
    base = {"run_id": "original-run", "planning_status": {"chosen_plan": {"plan_id": "p"}}}
    store.publish(base)
    event = StorageModeTransitionEvent(
        "event",
        datetime(2026, 9, 15, 17, 15, tzinfo=UTC),
        "Alleen slim ontladen",
        "Snel ontladen",
        "boundary",
        "due segment",
        None,
        "clock-run",
        "fresh-snapshot",
        None,
        "p",
        "application",
    )
    store.publish_storage_mode_transition_history((event,))
    view = json.loads(store.latest_json() or "{}")
    assert view["run_id"] == "original-run"
    assert view["planning_status"]["chosen_plan"] == {"plan_id": "p"}
    assert view["storage_mode_transition_history"][0]["requested_vendor_mode"] == "Snel ontladen"
    assert view["storage_mode_transition_history"][0]["confidence"] is None
    # An unrelated observer publication must not restore an older transition list.
    store.publish(base)
    assert (
        json.loads(store.latest_json() or "{}")["storage_mode_transition_history"]
        == view["storage_mode_transition_history"]
    )


def test_transition_render_distinguishes_unknown_from_zero_confidence() -> None:
    start = DASHBOARD_HTML.index("    function renderStorageModeTransitionHistory(")
    end = DASHBOARD_HTML.index("\n    function ", start + 10)
    function = DASHBOARD_HTML[start:end]
    formatter_start = DASHBOARD_HTML.index("    function formatConfidence(")
    formatter_end = DASHBOARD_HTML.index("\n    function ", formatter_start + 10)
    script = (
        """
const container = {children: [], replaceChildren(){this.children=[];},
 append(...x){this.children.push(...x);}};
const element = () => container;
const document = {createElement: () => ({children: [], append(...x){this.children.push(...x);}})};
const displayValue = x => x ?? "—";
"""
        + DASHBOARD_HTML[formatter_start:formatter_end]
        + function
        + """
renderStorageModeTransitionHistory([{occurred_at:"2026-09-15T17:15:00Z",confidence:null},
{occurred_at:"2026-09-15T17:16:00Z",confidence:0}]);
const rows = container.children[0].children[1].children;
console.log(JSON.stringify(rows.map(r => r.children[4].textContent)));
"""
    )
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run([node], input=script, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == ["0%", "—"]


def test_fresh_expectation_preserves_past_and_rejects_stale_or_other_plan() -> None:
    store = WebViewStore()
    old = {
        "captured_at": "2026-09-15T08:00:00+00:00",
        "soc_projection_captured_at": "2026-09-15T08:00:00+00:00",
        "chosen_plan": {"plan_id": "p", "energy_path_id": "path"},
        "decision": {"status": "plan_retained"},
        "soc_timeline": [
            {"at": "2026-09-15T08:00:00+00:00", "soc_percent": 40, "primitive": "actual"},
            {
                "at": "2026-09-15T10:00:00+00:00",
                "soc_percent": 80,
                "primitive": "balance_bidirectional",
            },
        ],
    }
    store.publish({"run_id": "original", "planning_status": old})
    patch = {
        "captured_at": "2026-09-15T09:00:00+00:00",
        "soc_projection_captured_at": "2026-09-15T09:00:00+00:00",
        "soc_projection_retained": False,
        "chosen_plan": {"plan_id": "p", "energy_path_id": "path"},
        "soc_expectation": {"status": "available", "snapshot_id": "new-facts"},
        "soc_timeline": [
            {"at": "2026-09-15T09:00:00+00:00", "soc_percent": 70, "primitive": "actual"},
            {
                "at": "2026-09-15T10:00:00+00:00",
                "soc_percent": 90,
                "primitive": "balance_bidirectional",
            },
        ],
    }
    store.publish_soc_expectation(patch)
    view = json.loads(store.latest_json() or "{}")
    assert view["run_id"] == "original"
    line = view["planning_status"]["soc_display_timeline"]
    assert [p["soc_percent"] for p in line] == [40, 60, 70, 90]
    assert line[2]["break_before"] is True
    # The old elapsed slope ends at 60; it is not redrawn to meet measured 70.
    store.publish({"run_id": "original", "planning_status": old})
    assert (
        json.loads(store.latest_json() or "{}")["planning_status"]["soc_timeline"]
        == patch["soc_timeline"]
    )
    before = store.latest_json()
    store.publish_soc_expectation(
        {**patch, "chosen_plan": {"plan_id": "other", "energy_path_id": "x"}}
    )
    assert store.latest_json() == before
    store.publish_soc_expectation({**patch, "soc_projection_captured_at": old["captured_at"]})
    assert store.latest_json() == before


def test_unavailable_fresh_expectation_does_not_restore_stale_future(tmp_path: Path) -> None:
    from picot.v2.soc_projection_cache import SOCProjectionCache

    store = WebViewStore(soc_cache=SOCProjectionCache(tmp_path / "soc.json"))
    status = {
        "captured_at": "2026-09-15T08:00:00+00:00",
        "soc_projection_captured_at": "2026-09-15T08:00:00+00:00",
        "chosen_plan": {
            "plan_id": "p",
            "energy_path_id": "path",
            "candidate_id": "c",
            "valid_from": "2026-09-15T08:00:00+00:00",
            "valid_until": "2026-09-15T12:00:00+00:00",
        },
        "decision": {"status": "winner_selected"},
        "soc_timeline": [
            {"at": "2026-09-15T08:00:00+00:00", "soc_percent": 40, "primitive": "actual"},
            {"at": "2026-09-15T10:00:00+00:00", "soc_percent": 80, "primitive": "nom"},
        ],
    }
    store.publish({"planning_status": status})
    patch = {
        "chosen_plan": status["chosen_plan"],
        "captured_at": "2026-09-15T09:00:00+00:00",
        "soc_projection_captured_at": "2026-09-15T09:00:00+00:00",
        "soc_expectation": {"status": "unavailable", "reason": "missing_pv"},
        "soc_timeline": [],
    }
    store.publish_soc_expectation(patch)
    store.publish(
        {
            "planning_status": {
                **status,
                "decision": {"status": "plan_retained"},
                "soc_timeline": [],
            }
        }
    )
    shown = json.loads(store.latest_json() or "{}")["planning_status"]
    assert shown["soc_timeline"] == []
    assert shown["soc_expectation"]["status"] == "unavailable"
    assert [p["soc_percent"] for p in shown["soc_display_timeline"]] == [40, 60]


def test_missing_committed_context_expires_only_future() -> None:
    store = WebViewStore()
    store.publish(
        {
            "planning_status": {
                "captured_at": "2026-09-15T08:00:00+00:00",
                "soc_projection_captured_at": "2026-09-15T08:00:00+00:00",
                "chosen_plan": {"plan_id": "p", "energy_path_id": "path"},
                "decision": {"status": "plan_retained"},
                "soc_timeline": [
                    {"at": "2026-09-15T08:00:00+00:00", "soc_percent": 40, "primitive": "actual"},
                    {"at": "2026-09-15T10:00:00+00:00", "soc_percent": 80, "primitive": "nom"},
                ],
            }
        }
    )
    store.publish_soc_expectation_unavailable(
        datetime(2026, 9, 15, 9, tzinfo=UTC), "committed_context_unavailable"
    )
    status = json.loads(store.latest_json() or "{}")["planning_status"]
    assert status["soc_timeline"] == []
    assert status["soc_expectation"]["reason"] == "committed_context_unavailable"
    assert [p["soc_percent"] for p in status["soc_display_timeline"]] == [40, 60]


def test_canonical_plan_expectation_reaches_display_without_replanning(tmp_path, monkeypatch):
    from test_daily_main_active_pipeline import setup
    from test_daily_main_charge_windows import inputs
    from test_daily_main_route_optimisation import fresh

    from picot.v2.soc_expectation import committed_soc_expectation
    from picot.v2.web_ui import _build_planning_status

    plans, pipeline, recover = setup(tmp_path, monkeypatch)
    source = recover()
    run = pipeline.run(planning_input=source)
    plan = run.execution_plan_set.plans[0]
    view = WebViewStore()
    view.publish(
        {"run_id": run.planning_input.run_id, "planning_status": _build_planning_status(run)}
    )
    unchanged_plan = plans.load_active_daily_main_plan(plan.execution_scope_id)
    fresh_input = recover(fresh(source, soc=0.65))
    patch = committed_soc_expectation(fresh_input, unchanged_plan, inputs()["conversion_model"])
    view.publish_soc_expectation(patch)
    shown = json.loads(view.latest_json() or "{}")["planning_status"]
    assert shown["chosen_plan"]["plan_id"] == plan.plan_id
    assert shown["soc_expectation"]["snapshot_id"] == fresh_input.snapshot_id
    assert shown["soc_timeline"][0]["soc_percent"] == 65
    assert shown["soc_display_timeline"][-1]["at"] == patch["soc_timeline"][-1]["at"]
    assert plans.load_active_daily_main_plan(plan.execution_scope_id) == unchanged_plan
