from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from picot.domain.planning_input_snapshot import RuntimePressureState
from picot.domain.runtime import (
    MaterialChangeClassification,
    PlannerRunState,
    ReplanningSignalStatus,
    RuntimeCoordinationState,
    RuntimeObservation,
    RuntimeObservationKind,
)
from picot.runtime.runtime_monitor import RuntimeMonitor

BASE = datetime(2026, 8, 2, 7, 0, tzinfo=UTC)


def _state(
    *,
    planner_state: PlannerRunState = PlannerRunState.IDLE,
    replan_required: bool = False,
    reasons: tuple[str, ...] = (),
    source_ids: tuple[str, ...] = (),
    active_run_id: str | None = None,
    ended_at: datetime | None = None,
    deadline: datetime | None = None,
) -> RuntimeCoordinationState:
    return RuntimeCoordinationState(
        planner_state=planner_state,
        active_planner_run_id=active_run_id,
        last_planner_run_started_at=None,
        last_planner_run_ended_at=ended_at,
        stabilisation_deadline=deadline,
        replan_required=replan_required,
        replan_reasons=reasons,
        source_observation_ids=source_ids,
        last_processed_observation_at=None,
        runtime_pressure_state=RuntimePressureState.NORMAL,
        state_version=1,
    )


def _observation(
    observation_id: str,
    kind: RuntimeObservationKind,
    *,
    new_value: str | None = None,
    material_transition: bool = False,
    actively_required: bool = False,
    observed_at: datetime = BASE,
) -> RuntimeObservation:
    return RuntimeObservation(
        observation_id=observation_id,
        kind=kind,
        observed_at=observed_at,
        source_reference="home-assistant",
        new_value=new_value,
        material_transition=material_transition,
        actively_required=actively_required,
    )


def test_material_change_requests_fresh_snapshot_from_idle() -> None:
    result = RuntimeMonitor().evaluate(
        (
            _observation(
                "observation-1",
                RuntimeObservationKind.PRICE_CHANGED,
                material_transition=True,
            ),
        ),
        _state(),
        now=BASE,
    )

    assert result.next_state.replan_required is True
    assert (
        result.replanning_signal.status
        is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
    )
    assert result.replanning_signal.fresh_snapshot_required is True
    assert (
        result.material_changes[0].classification
        is MaterialChangeClassification.MATERIAL_REPLAN
    )


def test_non_material_change_does_not_request_replanning() -> None:
    result = RuntimeMonitor().evaluate(
        (
            _observation(
                "observation-1",
                RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
            ),
        ),
        _state(),
        now=BASE,
    )

    assert result.next_state.replan_required is False
    assert result.replanning_signal.status is ReplanningSignalStatus.NONE


def test_safety_activation_requires_immediate_action_and_replanning() -> None:
    result = RuntimeMonitor().evaluate(
        (
            _observation(
                "observation-safety",
                RuntimeObservationKind.SAFETY_STATE_CHANGED,
                new_value="active",
            ),
        ),
        _state(),
        now=BASE,
    )

    assert result.immediate_protective_action_required is True
    assert (
        result.material_changes[0].classification
        is MaterialChangeClassification.IMMEDIATE_PROTECTIVE_ACTION
    )
    assert result.next_state.replan_required is True


def test_running_planner_blocks_new_run_but_keeps_pending_replan() -> None:
    state = _state(
        planner_state=PlannerRunState.RUNNING,
        active_run_id="planner-run-1",
    )
    result = RuntimeMonitor().evaluate(
        (
            _observation(
                "observation-commitment",
                RuntimeObservationKind.COMMITMENT_CHANGED,
            ),
        ),
        state,
        now=BASE,
    )

    assert (
        result.replanning_signal.status
        is ReplanningSignalStatus.BLOCKED_BY_RUNNING_PLANNER
    )
    assert result.next_state.replan_required is True


def test_planner_finish_enforces_exact_five_second_stabilisation() -> None:
    monitor = RuntimeMonitor()
    pending = _state(
        replan_required=True,
        reasons=("Price threshold crossed.",),
        source_ids=("observation-1",),
    )
    running = monitor.start_planner_run(
        pending,
        planner_run_id="planner-run-1",
        started_at=BASE,
    )
    stabilising = monitor.finish_planner_run(
        running,
        planner_run_id="planner-run-1",
        ended_at=BASE + timedelta(seconds=2),
    )

    assert stabilising.planner_state is PlannerRunState.STABILISING
    assert stabilising.stabilisation_deadline == BASE + timedelta(seconds=7)

    during = monitor.evaluate(
        (
            _observation(
                "observation-2",
                RuntimeObservationKind.STRATEGY_CHANGED,
                observed_at=BASE + timedelta(seconds=3),
            ),
        ),
        stabilising,
        now=BASE + timedelta(seconds=6),
    )
    assert (
        during.replanning_signal.status
        is ReplanningSignalStatus.BLOCKED_BY_STABILISATION
    )

    expired = monitor.evaluate((), during.next_state, now=BASE + timedelta(seconds=7))
    assert expired.next_state.planner_state is PlannerRunState.IDLE
    assert (
        expired.replanning_signal.status
        is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
    )


def test_monitor_rejects_duplicate_observations() -> None:
    observation = _observation(
        "observation-1",
        RuntimeObservationKind.PRICE_CHANGED,
        material_transition=True,
    )

    with pytest.raises(ValueError, match="must be unique"):
        RuntimeMonitor().evaluate((observation, observation), _state(), now=BASE)
