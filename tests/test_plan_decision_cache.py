"""Display evidence survives restart without acquiring planning authority."""

import json
from copy import deepcopy

import pytest
from test_plan_decision_dashboard import explanation, view

from picot.v2.plan_decision_cache import MAX_CACHE_BYTES, PlanDecisionCache
from picot.v2.soc_projection_cache import SOCProjectionCache
from picot.v2.web_ui import WebViewStore


def observation():
    result = view(explanation(source="observation", assessed_at="2026-10-31T15:00:00+00:00",
                              incumbent_cost_eur=None, alternative_cost_eur=None,
                              improvement_eur=None))
    result["planning_status"]["captured_at"] = "2026-10-31T15:00:00+00:00"
    return result["planning_status"]


def cache(path):
    return PlanDecisionCache(path)


def test_restart_restores_original_comparison_without_changing_input(tmp_path):
    path = tmp_path / "decision.json"
    original = view()["planning_status"]
    assert cache(path).apply(original) is original
    incoming = observation()
    before = deepcopy(incoming)
    restored = cache(path).apply(incoming)
    assert restored["plan_decision"] == {**original["plan_decision"], "evidence_retained": True}
    assert incoming == before
    assert restored["captured_at"] == incoming["captured_at"]


def test_fresh_comparison_replaces_cache_and_is_never_overwritten(tmp_path):
    path = tmp_path / "decision.json"
    cache(path).apply(view()["planning_status"])
    current = view(explanation(improvement_eur=0.2))["planning_status"]
    assert cache(path).apply(current) is current
    assert cache(path).apply(observation())["plan_decision"]["improvement_eur"] == 0.2


@pytest.mark.parametrize("mutation", [
    {"execution_plans": [{"plan_id": "new", "energy_path_id": "path-a"}]},
    {"execution_plans": [{"plan_id": "plan-a", "energy_path_id": "new"}]},
    {"execution_plans": []},
    {"decision": {"status": "fallback_active"}},
    {"decision": {"status": "winner_selected"}},
    {"captured_at": "2026-10-31T13:00:00+00:00"},
])
def test_cached_explanation_never_crosses_identity_state_or_time_boundary(tmp_path, mutation):
    path = tmp_path / "decision.json"
    cache(path).apply(view()["planning_status"])
    current = {**observation(), **mutation}
    assert cache(path).apply(current) is current


@pytest.mark.parametrize("status", ["publication_failed", "fallback", "unavailable"])
def test_failure_and_incomplete_decisions_are_not_saved_or_overwritten(tmp_path, status):
    path = tmp_path / "decision.json"
    current = view(explanation(status=status))["planning_status"]
    cache(path).apply(current)
    assert not path.exists()
    cache(path).apply(view()["planning_status"])
    current["plan_decision"]["source"] = "observation"
    assert cache(path).apply(current) is current


@pytest.mark.parametrize("data", [b"not-json", b"x" * (MAX_CACHE_BYTES + 1),
    b'{"schema_version":1,"plan_decision":{"improvement_eur":NaN}}',
    b'{"schema_version":123}', b'[]', b'[' * 2000 + b'0' + b']' * 2000],
    ids=["syntax", "oversize", "nan", "version", "list", "depth"])
def test_corrupt_or_oversized_cache_is_nonfatal(tmp_path, data):
    path = tmp_path / "decision.json"
    path.write_bytes(data)
    incoming = observation()
    assert cache(path).apply(incoming) is incoming


@pytest.mark.parametrize("changes", [
    {"assessed_at": "2999-01-01T00:00:00+00:00"},
    {"assessed_at": "2026-10-31T14:04:00"},
    {"improvement_eur": float("inf")},
    {"reason": "x" * MAX_CACHE_BYTES},
    {"execution_plans": [{"plan_id": "unrelated", "energy_path_id": "path-a"}]},
])
def test_invalid_new_evidence_is_not_persisted(tmp_path, changes):
    path = tmp_path / "decision.json"
    incoming = view()["planning_status"]
    incoming["plan_decision"] = {**incoming["plan_decision"], **changes}
    assert cache(path).apply(incoming) is incoming
    assert not path.exists()


def test_future_dated_disk_evidence_is_rejected(tmp_path):
    path = tmp_path / "decision.json"
    cache(path).apply(view()["planning_status"])
    saved = json.loads(path.read_text())
    saved["plan_decision"]["assessed_at"] = "2999-01-01T00:00:00+00:00"
    path.write_text(json.dumps(saved))
    incoming = observation()
    assert cache(path).apply(incoming) is incoming


def test_write_failure_cannot_break_publication(tmp_path):
    # A directory at the file path makes the atomic replace fail.
    path = tmp_path / "directory"
    path.mkdir()
    current = view()["planning_status"]
    assert cache(path).apply(current) is current


def test_web_store_uses_separate_sibling_cache_and_restores_after_restart(tmp_path):
    soc_path = tmp_path / "soc.json"
    store = WebViewStore(soc_cache=SOCProjectionCache(soc_path))
    store.publish(view())
    decision_path = soc_path.with_suffix(".plan-decision.json")
    assert decision_path.exists()
    # No SOC projection was supplied: only the separate explanation is saved.
    assert not soc_path.exists()
    restarted = WebViewStore(soc_cache=SOCProjectionCache(soc_path))
    restarted.publish({"planning_status": observation()})
    shown = json.loads(restarted.latest_json())["planning_status"]["plan_decision"]
    assert shown["assessed_at"] == explanation()["assessed_at"]
    assert shown["evidence_retained"] is True
