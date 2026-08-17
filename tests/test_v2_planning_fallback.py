from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from test_v2_delegated_storage_pipeline_integration import _snapshot

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.planning_fallback_notifications import PlanningFallbackNotifier
from picot.v2.projection import project
from picot.v2.web_ui import build_web_view


class _Response:
    status = 200


def _full_storage_run() -> object:
    source = _snapshot()
    assert source.capability_snapshot_set is not None
    full = replace(
        source,
        current_storage_states=tuple(
            replace(state, current_soc=1.0)
            for state in source.current_storage_states
        ),
        capability_snapshot_set=replace(
            source.capability_snapshot_set,
            capabilities=tuple(
                replace(
                    capability,
                    supported_primitives=(
                        *capability.supported_primitives,
                        ExecutionPrimitive.BALANCE_DISCHARGE_ONLY,
                    ),
                )
                for capability in source.capability_snapshot_set.capabilities
            ),
        ),
    )
    return CanonicalPipeline().run(
        planning_input=full,
        control_change_allowed=True,
    )


def test_baseline_without_calculated_outcome_is_explicit_fallback() -> None:
    run = _full_storage_run()

    assert run.outcomes.outcomes == ()
    assert run.evaluation.status == "fallback_active"
    assert run.evaluation.reason == (
        "no actionable candidate with a calculated outcome"
    )
    assert run.evaluation.decisive_step == "fallback:no_actionable_candidate"
    assert run.execution_record.status == "fallback_active"
    assert run.execution_plan_set.plans

    status = build_web_view(run, project(run))["planning_status"]
    assert status["attention"] == {
        "required": True,
        "code": "fallback_no_actionable_plan",
        "title": "Geen uitvoerbaar plan beschikbaar",
        "message": "De veilige terugvalmodus blijft actief; aandacht vereist.",
    }
    assert status["decision"]["confidence"] is None
    assert status["alternatives"][0]["confidence"] is None


def test_planning_fallback_notification_is_deduplicated_and_recovers() -> None:
    fallback = _full_storage_run()
    normal = CanonicalPipeline().run(planning_input=_snapshot())
    calls: list[dict[str, Any]] = []

    def opener(request: Any, timeout: float) -> _Response:
        assert timeout > 0
        calls.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    notifier = PlanningFallbackNotifier()
    now = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
    notifier.update("token", run=fallback, now=now, opener=opener)
    notifier.update("token", run=fallback, now=now, opener=opener)
    notifier.update("token", run=normal, now=now, opener=opener)

    assert len(calls) == 2
    assert calls[0]["notification_id"] == "picot_planning_fallback"
    assert "aandacht vereist" in calls[0]["title"]
    assert "terugvalmodus" in calls[0]["message"]
    assert "hersteld" in calls[1]["title"]
