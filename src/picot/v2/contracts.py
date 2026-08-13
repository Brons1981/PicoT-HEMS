"""Immutable contracts for the PicoT v2 canonical pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PriceForecastPoint:
    point_id: str
    starts_at: datetime
    ends_at: datetime
    value_eur_per_kwh: float
    confidence: float
    evidence_id: str


@dataclass(frozen=True, slots=True)
class PlanningInputSnapshot:
    run_id: str
    snapshot_id: str
    captured_at: datetime
    picot_version: str
    architecture_baseline_commit: str
    pipeline_contract_version: int
    strategy_id: str
    horizon_end: datetime | None = None
    price_points: tuple[PriceForecastPoint, ...] = ()


@dataclass(frozen=True, slots=True)
class OpportunityEvidenceRef:
    evidence_id: str
    point_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpportunityMetrics:
    duration_seconds: float
    average_price_eur_per_kwh: float
    minimum_price_eur_per_kwh: float
    maximum_price_eur_per_kwh: float
    boundary_eur_per_kwh: float | None
    source_interval_count: int
    bridged_interval_count: int


@dataclass(frozen=True, slots=True)
class Opportunity:
    opportunity_id: str
    run_id: str
    snapshot_id: str
    kind: str
    starts_at: datetime
    ends_at: datetime
    confidence: float
    lifecycle_status: str
    evidence: tuple[OpportunityEvidenceRef, ...]
    metrics: OpportunityMetrics


@dataclass(frozen=True, slots=True)
class OpportunitySet:
    run_id: str
    snapshot_id: str
    opportunity_set_id: str
    opportunity_ids: tuple[str, ...] = ()
    opportunities: tuple[Opportunity, ...] = ()
    detection_status: str = "ready"
    detection_reason: str | None = None
    detector_config_version: str | None = None


@dataclass(frozen=True, slots=True)
class EnergyPath:
    run_id: str
    snapshot_id: str
    path_id: str
    family: str
    segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidate:
    run_id: str
    snapshot_id: str
    candidate_id: str
    energy_path_id: str
    family: str


@dataclass(frozen=True, slots=True)
class CandidateSet:
    run_id: str
    snapshot_id: str
    candidate_set_id: str
    candidates: tuple[Candidate, ...]
    energy_paths: tuple[EnergyPath, ...]


@dataclass(frozen=True, slots=True)
class CandidateOutcomeSet:
    run_id: str
    snapshot_id: str
    candidate_set_id: str
    outcome_set_id: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    run_id: str
    snapshot_id: str
    evaluation_id: str
    candidate_set_id: str
    winning_candidate_id: str
    winning_energy_path_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionPlanSet:
    run_id: str
    snapshot_id: str
    plan_set_id: str
    evaluation_id: str
    winning_energy_path_id: str
    plan_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    run_id: str
    snapshot_id: str
    execution_record_id: str
    plan_set_id: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionPrimitiveBoundary:
    run_id: str
    snapshot_id: str
    request_id: str | None
    execution_record_id: str
    status: str


@dataclass(frozen=True, slots=True)
class DeviceAdapterBoundary:
    run_id: str
    snapshot_id: str
    translation_id: str | None
    primitive_request_id: str | None
    status: str


@dataclass(frozen=True, slots=True)
class VendorBoundaryResult:
    run_id: str
    snapshot_id: str
    command_id: str | None
    adapter_translation_id: str | None
    status: str
    observed_result_id: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalPipelineRun:
    planning_input: PlanningInputSnapshot
    opportunities: OpportunitySet
    candidate_set: CandidateSet
    outcomes: CandidateOutcomeSet
    evaluation: EvaluationRecord
    execution_plan_set: ExecutionPlanSet
    execution_record: ExecutionRecord
    primitive_boundary: ExecutionPrimitiveBoundary
    adapter_boundary: DeviceAdapterBoundary
    vendor_result: VendorBoundaryResult
