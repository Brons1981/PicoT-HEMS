"""Deterministic Runtime Monitor defined by ADR-028 and ADR-034."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from picot.domain.runtime import (
    MaterialChangeClassification,
    MaterialChangeRecord,
    PlannerRunState,
    ReplanningSignal,
    ReplanningSignalStatus,
    RuntimeCoordinationState,
    RuntimeMonitorResult,
    RuntimeObservation,
    RuntimeObservationKind,
)

IMPLEMENTATION_VERSION = "runtime-monitor-v1"
STABILISATION_INTERVAL = timedelta(seconds=5)


class RuntimeMonitor:
    """Classify runtime observations and coordinate deterministic replanning."""

    def evaluate(
        self,
        observations: tuple[RuntimeObservation, ...],
        state: RuntimeCoordinationState,
        *,
        now: datetime,
    ) -> RuntimeMonitorResult:
        self._validate_inputs(observations, state, now)
        state = self._expire_stabilisation(state, now)

        records = tuple(self._classify(item) for item in observations)
        reasons = list(state.replan_reasons)
        source_ids = list(state.source_observation_ids)
        immediate = False

        for observation, record in zip(observations, records, strict=True):
            if record.classification is MaterialChangeClassification.NON_MATERIAL:
                continue
            if record.reason not in reasons:
                reasons.append(record.reason)
            if observation.observation_id not in source_ids:
                source_ids.append(observation.observation_id)
            if (
                record.classification
                is MaterialChangeClassification.IMMEDIATE_PROTECTIVE_ACTION
            ):
                immediate = True

        last_observed_at = (
            observations[-1].observed_at
            if observations
            else state.last_processed_observation_at
        )
        next_state = replace(
            state,
            replan_required=bool(reasons),
            replan_reasons=tuple(reasons),
            source_observation_ids=tuple(source_ids),
            last_processed_observation_at=last_observed_at,
            state_version=state.state_version + 1,
        )
        signal = self._signal(next_state, now)
        return RuntimeMonitorResult(
            material_changes=records,
            next_state=next_state,
            replanning_signal=signal,
            immediate_protective_action_required=immediate,
            implementation_version=IMPLEMENTATION_VERSION,
        )

    def start_planner_run(
        self,
        state: RuntimeCoordinationState,
        *,
        planner_run_id: str,
        started_at: datetime,
    ) -> RuntimeCoordinationState:
        self._require_aware(started_at, "Planner Run start")
        if not planner_run_id.strip():
            raise ValueError("Planner Run ID must not be empty.")
        state = self._expire_stabilisation(state, started_at)
        if state.planner_state is not PlannerRunState.IDLE:
            raise ValueError("A Planner Run may start only from IDLE state.")
        if not state.replan_required:
            raise ValueError("A Planner Run requires a pending replan request.")
        return replace(
            state,
            planner_state=PlannerRunState.RUNNING,
            active_planner_run_id=planner_run_id,
            last_planner_run_started_at=started_at,
            stabilisation_deadline=None,
            replan_required=False,
            replan_reasons=(),
            source_observation_ids=(),
            state_version=state.state_version + 1,
        )

    def finish_planner_run(
        self,
        state: RuntimeCoordinationState,
        *,
        planner_run_id: str,
        ended_at: datetime,
    ) -> RuntimeCoordinationState:
        self._require_aware(ended_at, "Planner Run end")
        if state.planner_state is not PlannerRunState.RUNNING:
            raise ValueError("Only a RUNNING Planner Run may finish.")
        if state.active_planner_run_id != planner_run_id:
            raise ValueError("Planner Run ID must match the active Planner Run.")
        if (
            state.last_planner_run_started_at is not None
            and ended_at < state.last_planner_run_started_at
        ):
            raise ValueError("Planner Run may not end before it starts.")
        return replace(
            state,
            planner_state=PlannerRunState.STABILISING,
            active_planner_run_id=None,
            last_planner_run_ended_at=ended_at,
            stabilisation_deadline=ended_at + STABILISATION_INTERVAL,
            state_version=state.state_version + 1,
        )

    @staticmethod
    def _validate_inputs(
        observations: tuple[RuntimeObservation, ...],
        state: RuntimeCoordinationState,
        now: datetime,
    ) -> None:
        RuntimeMonitor._require_aware(now, "Runtime Monitor time")
        ids = [item.observation_id for item in observations]
        if len(ids) != len(set(ids)):
            raise ValueError("Runtime observation IDs must be unique.")
        times = [item.observed_at for item in observations]
        if times != sorted(times):
            raise ValueError("Runtime observations must be time ordered.")
        if any(item.observed_at > now for item in observations):
            raise ValueError("Runtime observations may not be in the future.")
        if state.last_processed_observation_at is not None and any(
            item.observed_at < state.last_processed_observation_at
            for item in observations
        ):
            raise ValueError(
                "Runtime observations may not precede the last processed observation."
            )

    @staticmethod
    def _classify(observation: RuntimeObservation) -> MaterialChangeRecord:
        kind = observation.kind
        new_value = (observation.new_value or "").strip().lower()

        if kind is RuntimeObservationKind.SAFETY_STATE_CHANGED and new_value in {
            "active",
            "activated",
            "true",
        }:
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.IMMEDIATE_PROTECTIVE_ACTION,
                "Safety state activated.",
            )
        if kind is RuntimeObservationKind.HARD_LIMIT_STATE_CHANGED and new_value in {
            "active",
            "violated",
            "true",
        }:
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.IMMEDIATE_PROTECTIVE_ACTION,
                "Hard-limit state violated.",
            )

        if kind in {
            RuntimeObservationKind.CAPABILITY_MAPPING_CHANGED,
            RuntimeObservationKind.USER_RULES_CHANGED,
            RuntimeObservationKind.STRATEGY_CHANGED,
            RuntimeObservationKind.COMMITMENT_CHANGED,
        }:
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.MATERIAL_REPLAN,
                f"{kind.value} requires replanning.",
            )

        if (
            kind
            in {
                RuntimeObservationKind.CAPABILITY_AVAILABILITY_CHANGED,
                RuntimeObservationKind.CAPABILITY_HEALTH_CHANGED,
            }
            and observation.actively_required
            and new_value in {"unavailable", "temporarily_unavailable", "unhealthy"}
        ):
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.MATERIAL_REPLAN,
                "An actively required capability can no longer support execution.",
            )

        if kind is RuntimeObservationKind.EXECUTION_OUTCOME_CHANGED and new_value in {
            "rejected",
            "failed",
            "timed_out",
            "timeout",
            "replan_required",
        }:
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.MATERIAL_REPLAN,
                f"Execution outcome {new_value} requires replanning.",
            )

        if kind in {
            RuntimeObservationKind.HOUSEHOLD_STATE_CHANGED,
            RuntimeObservationKind.FORECAST_CHANGED,
            RuntimeObservationKind.PRICE_CHANGED,
            RuntimeObservationKind.RUNTIME_PRESSURE_CHANGED,
        } and observation.material_transition:
            return MaterialChangeRecord(
                observation.observation_id,
                MaterialChangeClassification.MATERIAL_REPLAN,
                f"Accepted material transition for {kind.value}.",
            )

        return MaterialChangeRecord(
            observation.observation_id,
            MaterialChangeClassification.NON_MATERIAL,
            f"No accepted material transition for {kind.value}.",
        )

    @staticmethod
    def _expire_stabilisation(
        state: RuntimeCoordinationState,
        now: datetime,
    ) -> RuntimeCoordinationState:
        if (
            state.planner_state is PlannerRunState.STABILISING
            and state.stabilisation_deadline is not None
            and now >= state.stabilisation_deadline
        ):
            return replace(
                state,
                planner_state=PlannerRunState.IDLE,
                stabilisation_deadline=None,
                state_version=state.state_version + 1,
            )
        return state

    @staticmethod
    def _signal(
        state: RuntimeCoordinationState,
        now: datetime,
    ) -> ReplanningSignal:
        if not state.replan_required:
            status = ReplanningSignalStatus.NONE
        elif state.planner_state is PlannerRunState.RUNNING:
            status = ReplanningSignalStatus.BLOCKED_BY_RUNNING_PLANNER
        elif state.planner_state is PlannerRunState.STABILISING:
            status = ReplanningSignalStatus.BLOCKED_BY_STABILISATION
        elif state.planner_state is PlannerRunState.IDLE:
            status = ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
        else:
            status = ReplanningSignalStatus.PENDING
        has_signal = status is not ReplanningSignalStatus.NONE
        return ReplanningSignal(
            status=status,
            requested_at=now,
            reasons=state.replan_reasons if has_signal else (),
            source_observation_ids=(
                state.source_observation_ids if has_signal else ()
            ),
            fresh_snapshot_required=(
                status is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
            ),
        )

    @staticmethod
    def _require_aware(value: datetime, label: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware.")
