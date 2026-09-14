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
from picot.runtime.runtime_monitor import RuntimeMonitor, RuntimeMonitorSession

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


def test_live_session_retains_pending_replan_during_stabilisation() -> None:
    session = RuntimeMonitorSession()
    first = _observation(
        "material-household-1",
        RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
        material_transition=True,
    )

    initial_signal = session.observe((first,), now=BASE)
    assert initial_signal.status is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED

    session.start_requested_run(planner_run_id="run-1", started_at=BASE)
    session.finish_requested_run(planner_run_id="run-1", ended_at=BASE)

    second = _observation(
        "material-household-2",
        RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
        material_transition=True,
        observed_at=BASE + timedelta(seconds=1),
    )
    blocked = session.observe((second,), now=BASE + timedelta(seconds=1))
    released = session.observe((), now=BASE + timedelta(seconds=5))

    assert blocked.status is ReplanningSignalStatus.BLOCKED_BY_STABILISATION
    assert released.status is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
    assert released.source_observation_ids == ("material-household-2",)


def test_live_session_retries_failed_requested_run_after_stabilisation() -> None:
    session = RuntimeMonitorSession()
    session.observe(
        (
            _observation(
                "material-price-1",
                RuntimeObservationKind.PRICE_CHANGED,
                material_transition=True,
            ),
        ),
        now=BASE,
    )
    session.start_requested_run(planner_run_id="run-failed", started_at=BASE)
    session.finish_requested_run(
        planner_run_id="run-failed",
        ended_at=BASE,
        execution_succeeded=False,
    )

    blocked = session.observe((), now=BASE + timedelta(seconds=4))
    retry = session.observe((), now=BASE + timedelta(seconds=5))

    assert blocked.status is ReplanningSignalStatus.BLOCKED_BY_STABILISATION
    assert retry.status is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
    assert retry.source_observation_ids == (
        "planner-run:run-failed:execution-failed",
    )


def _execution_status(status, at, *, source="plan-1"):
    return RuntimeObservation(
        observation_id=f"{source}:{at.isoformat()}:{status}",
        kind=RuntimeObservationKind.EXECUTION_OUTCOME_CHANGED,
        observed_at=at,
        source_reference=source,
        new_value=status,
    )


def test_latched_clock_timeout_does_not_replan_again_after_failed_cycle():
    session = RuntimeMonitorSession()
    first = session.observe((_execution_status("timed_out", BASE),), now=BASE)
    assert first.fresh_snapshot_required
    session.start_requested_run(planner_run_id="run-timeout", started_at=BASE)
    session.finish_requested_run(
        planner_run_id="run-timeout", ended_at=BASE, execution_succeeded=False
    )
    at = BASE + timedelta(seconds=5)
    repeated = session.observe((_execution_status("timed_out", at),), now=at)
    assert not repeated.fresh_snapshot_required
    assert session.state.last_processed_observation_at == at
    assert session.last_admission == first


@pytest.mark.parametrize("status,source", [("failed", "plan-1"), ("timed_out", "plan-2")])
def test_distinct_execution_failure_still_requests_replanning(status, source):
    session = RuntimeMonitorSession()
    session.observe((_execution_status("timed_out", BASE),), now=BASE)
    session.start_requested_run(planner_run_id="run-1", started_at=BASE)
    session.finish_requested_run(planner_run_id="run-1", ended_at=BASE, execution_succeeded=False)
    at = BASE + timedelta(seconds=5)
    changed = session.observe((_execution_status(status, at, source=source),), now=at)
    assert changed.fresh_snapshot_required


@pytest.mark.parametrize("recovery", ["dispatched", "already_active", "accepted", "succeeded"])
def test_execution_recovery_allows_a_subsequent_identical_failure(recovery):
    session = RuntimeMonitorSession()
    session.observe((_execution_status("failed", BASE),), now=BASE)
    session.start_requested_run(planner_run_id="run-1", started_at=BASE)
    session.finish_requested_run(planner_run_id="run-1", ended_at=BASE, execution_succeeded=False)
    session.observe(
        (_execution_status(recovery, BASE + timedelta(seconds=1)),), now=BASE + timedelta(seconds=1)
    )
    at = BASE + timedelta(seconds=5)
    changed = session.observe((_execution_status("failed", at),), now=at)
    assert changed.fresh_snapshot_required


def test_generic_failed_replan_is_reported_once_until_success():
    session = RuntimeMonitorSession()
    session.observe((_observation("start", RuntimeObservationKind.COMMITMENT_CHANGED),), now=BASE)
    session.start_requested_run(planner_run_id="run-1", started_at=BASE)
    session.finish_requested_run(planner_run_id="run-1", ended_at=BASE, execution_succeeded=False)
    at = BASE + timedelta(seconds=5)
    assert session.observe((), now=at).fresh_snapshot_required
    session.start_requested_run(planner_run_id="run-2", started_at=at)
    session.finish_requested_run(planner_run_id="run-2", ended_at=at, execution_succeeded=False)
    at += timedelta(seconds=5)
    assert not session.observe((), now=at).fresh_snapshot_required
    session.observe(
        (_observation("new-plan", RuntimeObservationKind.COMMITMENT_CHANGED, observed_at=at),),
        now=at,
    )
    session.start_requested_run(planner_run_id="run-3", started_at=at)
    session.finish_requested_run(planner_run_id="run-3", ended_at=at, execution_succeeded=True)
    at += timedelta(seconds=5)
    session.observe(
        (_observation("new-plan-2", RuntimeObservationKind.COMMITMENT_CHANGED, observed_at=at),),
        now=at,
    )
    session.start_requested_run(planner_run_id="run-4", started_at=at)
    session.finish_requested_run(planner_run_id="run-4", ended_at=at, execution_succeeded=False)
    assert session.state.replan_required


def test_repeated_execution_status_still_validates_observation_order():
    session = RuntimeMonitorSession()
    session.observe((_execution_status("failed", BASE),), now=BASE)
    late = BASE + timedelta(seconds=2)
    session.observe((_execution_status("failed", late),), now=late)
    with pytest.raises(ValueError, match="precede"):
        session.observe((_execution_status("failed", BASE),), now=late)
