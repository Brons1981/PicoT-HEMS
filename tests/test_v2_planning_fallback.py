from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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


def _missing_forecast_fallback_run() -> object:
    source = _snapshot()
    assert source.capability_snapshot_set is not None
    invalid = replace(
        source,
        household_load_forecast=None,
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
        planning_input=invalid,
        control_change_allowed=True,
    )


def test_full_storage_without_charge_action_is_valid_plan() -> None:
    run = _full_storage_run()

    assert run.candidate_set.derivation_status == "ready"
    assert run.candidate_set.storage_requirements
    assert all(
        state.current_soc >= requirement.required_soc
        for state in run.planning_input.current_storage_states
        for requirement in run.candidate_set.storage_requirements
        if state.storage_state_id == requirement.storage_state_id
    )
    assert run.outcomes.outcomes == ()
    assert run.evaluation.status == "winner_selected"
    assert run.evaluation.reason == (
        "storage requirement already satisfied; "
        "no additional charge action required"
    )
    assert run.evaluation.decisive_step == (
        "hard_constraint:storage_requirement_already_satisfied"
    )
    assert run.execution_record.status == "live_plan_ready"
    assert run.execution_plan_set.plans

    status = build_web_view(run, project(run))["planning_status"]
    assert status["attention"] == {
        "required": False,
        "code": None,
        "title": None,
        "message": None,
    }
    assert status["decision"]["confidence"] is None
    assert status["alternatives"][0]["confidence"] is None


def test_full_storage_builds_tomorrow_pv_plan_after_current_support_phase() -> None:
    source = _snapshot()
    base = source.captured_at
    pv_template = source.pv_energy_timeline.intervals[0]
    load_template = source.household_load_forecast.intervals[0]
    full = replace(
        source,
        horizon_end=base + timedelta(hours=3),
        current_storage_states=tuple(
            replace(state, current_soc=1.0)
            for state in source.current_storage_states
        ),
        pv_energy_timeline=replace(
            source.pv_energy_timeline,
            intervals=tuple(
                replace(
                    pv_template,
                    interval_id=f"pv-{index}",
                    starts_at=base + timedelta(hours=index),
                    ends_at=base + timedelta(hours=index + 1),
                    pv_energy_wh=pv_wh,
                )
                for index, pv_wh in enumerate((0.0, 800.0, 0.0))
            ),
        ),
        household_load_forecast=replace(
            source.household_load_forecast,
            intervals=tuple(
                replace(
                    load_template,
                    interval_id=f"load-{index}",
                    starts_at=base + timedelta(hours=index),
                    ends_at=base + timedelta(hours=index + 1),
                    expected_energy_wh=200.0,
                    source_reference=f"load-{index}",
                )
                for index in range(3)
            ),
        ),
    )

    run = CanonicalPipeline().run(planning_input=full)

    assert run.evaluation.status == "winner_selected"
    assert run.execution_record.status == "observer_only_plan_ready"
    assert run.outcomes.outcomes
    outcome = run.outcomes.outcomes[0]
    assert outcome.charge_window_starts_at == base + timedelta(hours=1)
    assert outcome.charge_window_ends_at == base + timedelta(hours=2)
    assert outcome.pv_storage_contribution_wh == 200.0
    assert outcome.requirement_satisfied is True
    assert outcome.confidence > 0.0


def test_planning_fallback_notification_is_deduplicated_and_recovers() -> None:
    fallback = _missing_forecast_fallback_run()
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
    assert "2026-08-17T22:00:00+02:00" in calls[0]["message"]
    assert "UTC 2026-08-17T20:00:00+00:00" in calls[0]["message"]
    assert "hersteld" in calls[1]["title"]
