from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import picot.addon.live_execution_plan_observer as observer
from picot.domain.evaluation import EvaluationOutcomeStatus


def test_no_planning_result_stays_non_executable() -> None:
    plan_set, fields = observer.observe_execution_plan_set(
        None,
        created_at=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
    )

    assert plan_set is None
    assert fields["execution_plan_set_available"] is False
    assert fields["execution_plan_count"] == 0
    assert fields["execution_fallback_policy_id"] == observer.FALLBACK_POLICY_ID
    assert fields["execution_plan_construction_status"] == "planning_result_unavailable"


def test_winner_uses_explicit_adr046_policy_and_accepts_empty_plan_set(monkeypatch: Any) -> None:
    calls: dict[str, object] = {}
    empty_plan_set = SimpleNamespace(plan_set_id="plan-set-test", plans=())

    class StubBuilder:
        def build(self, evaluation: object, *, created_at: datetime, fallback_policy_id: str) -> object:
            calls["evaluation"] = evaluation
            calls["created_at"] = created_at
            calls["fallback_policy_id"] = fallback_policy_id
            return empty_plan_set

    monkeypatch.setattr(observer, "_builder", StubBuilder())
    evaluation = SimpleNamespace(status=EvaluationOutcomeStatus.WINNER_SELECTED)
    planning_result = SimpleNamespace(evaluation=evaluation)
    created_at = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)

    plan_set, fields = observer.observe_execution_plan_set(
        cast(Any, planning_result),
        created_at=created_at,
    )

    assert plan_set is empty_plan_set
    assert calls["evaluation"] is evaluation
    assert calls["created_at"] == created_at
    assert calls["fallback_policy_id"] == "execution-fallback:hold-and-replan:v1"
    assert fields["execution_plan_set_available"] is True
    assert fields["execution_plan_set_id"] == "plan-set-test"
    assert fields["execution_plan_count"] == 0
    assert fields["execution_plan_construction_status"] == "constructed"
