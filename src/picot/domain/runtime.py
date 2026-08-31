"""Immutable runtime monitoring records defined by ADR-034."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from picot.domain.planning_input_snapshot import RuntimePressureState


class RuntimeObservationKind(StrEnum):
    CAPABILITY_AVAILABILITY_CHANGED = "capability_availability_changed"
    CAPABILITY_HEALTH_CHANGED = "capability_health_changed"
    CAPABILITY_MAPPING_CHANGED = "capability_mapping_changed"
    HOUSEHOLD_STATE_CHANGED = "household_state_changed"
    STORAGE_STATE_CHANGED = "storage_state_changed"
    FORECAST_CHANGED = "forecast_changed"
    PRICE_CHANGED = "price_changed"
    USER_RULES_CHANGED = "user_rules_changed"
    STRATEGY_CHANGED = "strategy_changed"
    COMMITMENT_CHANGED = "commitment_changed"
    EXECUTION_OUTCOME_CHANGED = "execution_outcome_changed"
    SAFETY_STATE_CHANGED = "safety_state_changed"
    HARD_LIMIT_STATE_CHANGED = "hard_limit_state_changed"
    RUNTIME_PRESSURE_CHANGED = "runtime_pressure_changed"


class MaterialChangeClassification(StrEnum):
    NON_MATERIAL = "non_material"
    MATERIAL_REPLAN = "material_replan"
    IMMEDIATE_PROTECTIVE_ACTION = "immediate_protective_action"


class PlannerRunState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STABILISING = "stabilising"


class ReplanningSignalStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    FRESH_SNAPSHOT_REQUIRED = "fresh_snapshot_required"
    BLOCKED_BY_RUNNING_PLANNER = "blocked_by_running_planner"
    BLOCKED_BY_STABILISATION = "blocked_by_stabilisation"


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    observation_id: str
    kind: RuntimeObservationKind
    observed_at: datetime
    source_reference: str
    old_value: str | None = None
    new_value: str | None = None
    unit: str | None = None
    execution_scope_id: str | None = None
    capability_id: str | None = None
    source_version: int | None = None
    evidence_ids: tuple[str, ...] = ()
    material_transition: bool = False
    actively_required: bool = False

    def __post_init__(self) -> None:
        for required_value, label in (
            (self.observation_id, "Observation ID"),
            (self.source_reference, "Source reference"),
        ):
            if not required_value.strip():
                raise ValueError(f"{label} must not be empty.")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Observation timestamp must be timezone-aware.")
        for optional_value, label in (
            (self.unit, "Unit"),
            (self.execution_scope_id, "Execution scope ID"),
            (self.capability_id, "Capability ID"),
        ):
            if optional_value is not None and not optional_value.strip():
                raise ValueError(f"{label} must not be empty when provided.")
        if self.source_version is not None and self.source_version < 1:
            raise ValueError("Source version must be at least 1 when provided.")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("Evidence IDs must not be empty.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Evidence IDs must be unique.")


@dataclass(frozen=True, slots=True)
class MaterialChangeRecord:
    observation_id: str
    classification: MaterialChangeClassification
    reason: str

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("Material-change observation ID must not be empty.")
        if not self.reason.strip():
            raise ValueError("Material-change reason must not be empty.")


@dataclass(frozen=True, slots=True)
class RuntimeCoordinationState:
    planner_state: PlannerRunState
    active_planner_run_id: str | None
    last_planner_run_started_at: datetime | None
    last_planner_run_ended_at: datetime | None
    stabilisation_deadline: datetime | None
    replan_required: bool
    replan_reasons: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    last_processed_observation_at: datetime | None
    runtime_pressure_state: RuntimePressureState
    state_version: int

    def __post_init__(self) -> None:
        if self.state_version < 1:
            raise ValueError("Runtime coordination state version must be at least 1.")
        if self.planner_state is PlannerRunState.RUNNING:
            if self.active_planner_run_id is None or not self.active_planner_run_id.strip():
                raise ValueError("RUNNING state requires an active Planner Run ID.")
            if self.stabilisation_deadline is not None:
                raise ValueError("RUNNING state may not contain a stabilisation deadline.")
        elif self.active_planner_run_id is not None:
            raise ValueError("Only RUNNING state may contain an active Planner Run ID.")
        if self.planner_state is PlannerRunState.STABILISING:
            if self.last_planner_run_ended_at is None or self.stabilisation_deadline is None:
                raise ValueError("STABILISING state requires run end and deadline timestamps.")
        elif self.stabilisation_deadline is not None:
            raise ValueError("Only STABILISING state may contain a stabilisation deadline.")
        for value, label in (
            (self.last_planner_run_started_at, "Last Planner Run start"),
            (self.last_planner_run_ended_at, "Last Planner Run end"),
            (self.stabilisation_deadline, "Stabilisation deadline"),
            (self.last_processed_observation_at, "Last processed observation"),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{label} must be timezone-aware.")
        if self.replan_required and not self.replan_reasons:
            raise ValueError("A pending replan requires at least one reason.")
        if not self.replan_required and (self.replan_reasons or self.source_observation_ids):
            raise ValueError("A state without pending replan may not contain replan evidence.")
        if any(not reason.strip() for reason in self.replan_reasons):
            raise ValueError("Replan reasons must not be empty.")
        if len(self.replan_reasons) != len(set(self.replan_reasons)):
            raise ValueError("Replan reasons must be unique and ordered.")
        if any(not item.strip() for item in self.source_observation_ids):
            raise ValueError("Source observation IDs must not be empty.")
        if len(self.source_observation_ids) != len(set(self.source_observation_ids)):
            raise ValueError("Source observation IDs must be unique and ordered.")


@dataclass(frozen=True, slots=True)
class ReplanningSignal:
    status: ReplanningSignalStatus
    requested_at: datetime
    reasons: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    fresh_snapshot_required: bool

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Replanning signal timestamp must be timezone-aware.")
        if self.status is ReplanningSignalStatus.NONE:
            if self.reasons or self.source_observation_ids or self.fresh_snapshot_required:
                raise ValueError("NONE signal may not contain replan details.")
        elif not self.reasons:
            raise ValueError("A non-empty replanning signal requires reasons.")
        if self.fresh_snapshot_required != (
            self.status is ReplanningSignalStatus.FRESH_SNAPSHOT_REQUIRED
        ):
            raise ValueError("Fresh-snapshot flag must match the signal status.")


@dataclass(frozen=True, slots=True)
class RuntimeMonitorResult:
    material_changes: tuple[MaterialChangeRecord, ...]
    next_state: RuntimeCoordinationState
    replanning_signal: ReplanningSignal
    immediate_protective_action_required: bool
    implementation_version: str

    def __post_init__(self) -> None:
        if not self.implementation_version.strip():
            raise ValueError("Runtime Monitor implementation version must not be empty.")
