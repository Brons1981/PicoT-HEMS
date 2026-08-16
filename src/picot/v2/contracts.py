"""Immutable contracts for the PicoT v2 canonical pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from picot.v2.zendure_mode_capabilities import ZendureModeCapabilityEvidence


@dataclass(frozen=True, slots=True)
class PriceForecastPoint:
    point_id: str
    starts_at: datetime
    ends_at: datetime
    value_eur_per_kwh: float
    confidence: float
    evidence_id: str


@dataclass(frozen=True, slots=True)
class CurrentStorageState:
    storage_state_id: str
    execution_scope_id: str
    capability_id: str
    current_soc: float
    usable_capacity_wh: float
    measured_at: datetime
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.current_soc <= 1.0:
            raise ValueError("current_soc must be between 0.0 and 1.0")
        if self.usable_capacity_wh <= 0.0:
            raise ValueError("usable_capacity_wh must be positive")

    @property
    def current_stored_energy_wh(self) -> float:
        return self.current_soc * self.usable_capacity_wh


@dataclass(frozen=True, slots=True)
class PVEnergyTimelineInterval:
    interval_id: str
    starts_at: datetime
    ends_at: datetime
    pv_energy_wh: float
    evidence_type: str
    confidence: float
    actual_evidence_ids: tuple[str, ...]
    forecast_evidence_ids: tuple[str, ...]
    conversion_method_version: str | None
    forecast_lower_energy_wh: float | None = None
    forecast_central_energy_wh: float | None = None
    forecast_upper_energy_wh: float | None = None
    forecast_range_status: str = "unavailable"
    forecast_range_source_fields: tuple[str, ...] = ()
    forecast_range_method_version: str | None = None

    def __post_init__(self) -> None:
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        if self.pv_energy_wh < 0.0:
            raise ValueError("pv_energy_wh must not be negative")
        if self.forecast_range_status not in ("available", "unavailable"):
            raise ValueError("forecast_range_status must be available or unavailable")
        if self.forecast_range_status == "available":
            if self.evidence_type != "FORECAST":
                raise ValueError("available forecast range requires FORECAST evidence")
            forecast_values = (
                self.forecast_lower_energy_wh,
                self.forecast_central_energy_wh,
                self.forecast_upper_energy_wh,
            )
            if any(value is None for value in forecast_values):
                raise ValueError(
                    "available forecast range requires lower, central, and upper energy"
                )
            lower, central, upper = forecast_values
            assert lower is not None
            assert central is not None
            assert upper is not None
            if not 0.0 <= lower <= central <= upper:
                raise ValueError("forecast range must satisfy 0 <= lower <= central <= upper")
            if central != self.pv_energy_wh:
                raise ValueError("forecast central energy must equal pv_energy_wh")
            if not self.forecast_range_source_fields:
                raise ValueError("available forecast range requires source fields")
            if not self.forecast_range_method_version:
                raise ValueError("available forecast range requires method version")
        if self.evidence_type not in ("ACTUAL", "FORECAST", "MIXED"):
            raise ValueError("evidence_type must be ACTUAL, FORECAST, or MIXED")
        if self.evidence_type == "ACTUAL" and not self.actual_evidence_ids:
            raise ValueError("ACTUAL interval requires actual evidence")
        if self.evidence_type == "FORECAST" and not self.forecast_evidence_ids:
            raise ValueError("FORECAST interval requires forecast evidence")
        if self.evidence_type == "MIXED" and (
            not self.actual_evidence_ids or not self.forecast_evidence_ids
        ):
            raise ValueError("MIXED interval requires actual and forecast evidence")


@dataclass(frozen=True, slots=True)
class PVEnergyTimeline:
    timeline_id: str
    run_id: str
    snapshot_id: str
    intervals: tuple[PVEnergyTimelineInterval, ...]

    def __post_init__(self) -> None:
        for previous, current in zip(
            self.intervals,
            self.intervals[1:],
            strict=False,
        ):
            if current.starts_at < previous.starts_at:
                raise ValueError("intervals must be chronologically ordered")
            if current.starts_at < previous.ends_at:
                raise ValueError("intervals must not overlap")


@dataclass(frozen=True, slots=True)
class PVAttenuationObservation:
    observation_id: str
    installation_scope_id: str
    starts_at: datetime
    ends_at: datetime
    forecast_captured_at: datetime
    forecast_lower_energy_wh: float
    forecast_central_energy_wh: float
    forecast_upper_energy_wh: float
    forecast_confidence: float
    actual_energy_wh: float
    actual_confidence: float
    solar_azimuth_degrees: float
    solar_elevation_degrees: float
    minutes_from_sunset: float
    forecast_evidence_ids: tuple[str, ...]
    actual_evidence_ids: tuple[str, ...]
    forecast_mapping_version: str
    forecast_conversion_method_version: str
    actual_conversion_method_version: str
    eligibility_status: str
    eligibility_reason: str | None
    eligibility_method_version: str
    alignment_status: str = "aligned"
    coverage_status: str = "complete"
    observation_method_version: str = "pv-attenuation-observation:v1"
    solar_evidence_id: str = "solar-evidence-unavailable"
    solar_observed_at: datetime | None = None
    sunset_at: datetime | None = None
    solar_alignment_method_version: str = "solar-alignment-unavailable"

    def __post_init__(self) -> None:
        datetimes = (
            self.starts_at,
            self.ends_at,
            self.forecast_captured_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in datetimes):
            raise ValueError("observation datetimes must be timezone-aware")
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        forecast_values = (
            self.forecast_lower_energy_wh,
            self.forecast_central_energy_wh,
            self.forecast_upper_energy_wh,
        )
        if (
            not all(isfinite(value) for value in forecast_values)
            or not 0.0
            <= self.forecast_lower_energy_wh
            <= self.forecast_central_energy_wh
            <= self.forecast_upper_energy_wh
        ):
            raise ValueError("forecast range must satisfy 0 <= lower <= central <= upper")
        if not isfinite(self.actual_energy_wh) or self.actual_energy_wh < 0.0:
            raise ValueError("actual_energy_wh must not be negative")
        if not 0.0 <= self.forecast_confidence <= 1.0:
            raise ValueError("forecast_confidence must be between 0 and 1")
        if not 0.0 <= self.actual_confidence <= 1.0:
            raise ValueError("actual_confidence must be between 0 and 1")
        if (
            not isfinite(self.solar_azimuth_degrees)
            or not 0.0 <= self.solar_azimuth_degrees <= 360.0
        ):
            raise ValueError("solar_azimuth_degrees must be between 0 and 360")
        if (
            not isfinite(self.solar_elevation_degrees)
            or not -90.0 <= self.solar_elevation_degrees <= 90.0
        ):
            raise ValueError("solar_elevation_degrees must be between -90 and 90")
        if not isfinite(self.minutes_from_sunset):
            raise ValueError("minutes_from_sunset must be finite")
        solar_datetimes = (self.solar_observed_at, self.sunset_at)
        if self.solar_observed_at is not None and self.sunset_at is None:
            raise ValueError("solar observation requires sunset_at")
        if any(
            value is not None and (value.tzinfo is None or value.utcoffset() is None)
            for value in solar_datetimes
        ):
            raise ValueError("solar lineage datetimes must be timezone-aware")
        if not self.solar_evidence_id.strip():
            raise ValueError("solar evidence must be explicit")
        if not self.forecast_evidence_ids:
            raise ValueError("forecast evidence must be explicit")
        if not self.actual_evidence_ids:
            raise ValueError("actual evidence must be explicit")
        if self.alignment_status not in ("aligned", "unaligned"):
            raise ValueError("alignment_status must be aligned or unaligned")
        if self.coverage_status not in ("complete", "partial"):
            raise ValueError("coverage_status must be complete or partial")
        if self.eligibility_status not in (
            "unassessed",
            "eligible",
            "rejected",
        ):
            raise ValueError("eligibility_status must be unassessed, eligible, or rejected")
        if self.eligibility_status == "unassessed" and not self.eligibility_reason:
            raise ValueError("unassessed observation requires eligibility_reason")
        if self.eligibility_status == "rejected" and not self.eligibility_reason:
            raise ValueError("rejected observation requires eligibility_reason")
        versions = (
            self.forecast_mapping_version,
            self.forecast_conversion_method_version,
            self.actual_conversion_method_version,
            self.solar_alignment_method_version,
            self.eligibility_method_version,
            self.observation_method_version,
        )
        if any(not value.strip() for value in versions):
            raise ValueError("method versions must be explicit")


@dataclass(frozen=True, slots=True)
class PVAttenuationBucket:
    bucket_id: str
    installation_scope_id: str
    sunset_offset_starts_minutes: float
    sunset_offset_ends_minutes: float
    attenuation_factor: float
    status: str
    unavailable_reason: str | None
    sample_count: int
    distinct_day_count: int
    dispersion: float
    profile_confidence: float
    evidence_starts_at: datetime
    evidence_ends_at: datetime
    updated_at: datetime
    observation_ids: tuple[str, ...]
    rejected_observation_ids: tuple[str, ...]
    aggregation_method_version: str
    configuration_version: str

    def __post_init__(self) -> None:
        if (
            not isfinite(self.sunset_offset_starts_minutes)
            or not isfinite(self.sunset_offset_ends_minutes)
            or self.sunset_offset_starts_minutes >= self.sunset_offset_ends_minutes
        ):
            raise ValueError("sunset offset start must be before end")
        if not isfinite(self.attenuation_factor) or not 0.0 <= self.attenuation_factor <= 1.0:
            raise ValueError("attenuation_factor must be between 0 and 1")
        if self.sample_count < 0:
            raise ValueError("sample_count must not be negative")
        if self.distinct_day_count < 0 or self.distinct_day_count > self.sample_count:
            raise ValueError("distinct_day_count must not exceed sample_count")
        if not isfinite(self.dispersion) or self.dispersion < 0.0:
            raise ValueError("dispersion must not be negative")
        if not isfinite(self.profile_confidence) or not 0.0 <= self.profile_confidence <= 1.0:
            raise ValueError("profile_confidence must be between 0 and 1")
        datetimes = (
            self.evidence_starts_at,
            self.evidence_ends_at,
            self.updated_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in datetimes):
            raise ValueError("bucket datetimes must be timezone-aware")
        if self.evidence_starts_at >= self.evidence_ends_at:
            raise ValueError("evidence_starts_at must be before evidence_ends_at")
        if self.status not in ("available", "unavailable"):
            raise ValueError("bucket status must be available or unavailable")
        if self.status == "unavailable":
            if not self.unavailable_reason:
                raise ValueError("unavailable bucket requires unavailable_reason")
            if self.attenuation_factor != 1.0:
                raise ValueError("unavailable bucket must use attenuation_factor 1")
        if not self.aggregation_method_version.strip():
            raise ValueError("aggregation_method_version must be explicit")
        if not self.configuration_version.strip():
            raise ValueError("configuration_version must be explicit")


@dataclass(frozen=True, slots=True)
class PVForecastAttenuationProfile:
    profile_id: str
    installation_scope_id: str
    status: str
    unavailable_reason: str | None
    valid_from: datetime
    valid_until: datetime
    updated_at: datetime
    observer_only: bool
    buckets: tuple[PVAttenuationBucket, ...]
    method_version: str

    def __post_init__(self) -> None:
        datetimes = (
            self.valid_from,
            self.valid_until,
            self.updated_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in datetimes):
            raise ValueError("profile datetimes must be timezone-aware")
        if self.valid_from >= self.valid_until:
            raise ValueError("valid_from must be before valid_until")
        if not self.observer_only:
            raise ValueError("attenuation profile must remain observer-only")
        if self.status not in ("available", "unavailable"):
            raise ValueError("profile status must be available or unavailable")
        if self.status == "unavailable" and not self.unavailable_reason:
            raise ValueError("unavailable profile requires unavailable_reason")
        if self.status == "available" and not self.buckets:
            raise ValueError("available profile requires attenuation buckets")
        for previous, current in zip(
            self.buckets,
            self.buckets[1:],
            strict=False,
        ):
            if current.sunset_offset_starts_minutes < previous.sunset_offset_starts_minutes:
                raise ValueError("profile buckets must be chronologically ordered")
            if current.sunset_offset_starts_minutes < previous.sunset_offset_ends_minutes:
                raise ValueError("profile buckets must not overlap")
        if any(
            bucket.installation_scope_id != self.installation_scope_id for bucket in self.buckets
        ):
            raise ValueError("bucket installation scope must match profile")
        if not self.method_version.strip():
            raise ValueError("method_version must be explicit")


@dataclass(frozen=True, slots=True)
class HouseholdLoadForecastInterval:
    interval_id: str
    starts_at: datetime
    ends_at: datetime
    expected_energy_wh: float
    confidence: float
    source_reference: str
    method_version: str

    def __post_init__(self) -> None:
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        if self.expected_energy_wh < 0.0:
            raise ValueError("expected_energy_wh must not be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.source_reference.strip():
            raise ValueError("source_reference must be explicit")
        if not self.method_version.strip():
            raise ValueError("method_version must be explicit")


@dataclass(frozen=True, slots=True)
class HouseholdLoadForecast:
    forecast_id: str
    run_id: str
    snapshot_id: str
    intervals: tuple[HouseholdLoadForecastInterval, ...]
    fallback_active: bool
    fallback_reason: str | None

    def __post_init__(self) -> None:
        if self.fallback_active and not (self.fallback_reason and self.fallback_reason.strip()):
            raise ValueError("fallback_reason is required when fallback is active")
        for previous, current in zip(
            self.intervals,
            self.intervals[1:],
            strict=False,
        ):
            if current.starts_at < previous.starts_at:
                raise ValueError("intervals must be chronologically ordered")
            if current.starts_at < previous.ends_at:
                raise ValueError("intervals must not overlap")


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
    current_storage_states: tuple[CurrentStorageState, ...] = ()
    pv_energy_timeline: PVEnergyTimeline | None = None
    household_load_forecast: HouseholdLoadForecast | None = None
    storage_mode_capability_evidence: ZendureModeCapabilityEvidence | None = None

    def __post_init__(self) -> None:
        for state in self.current_storage_states:
            if state.measured_at > self.captured_at:
                raise ValueError(
                    f"current storage state {state.storage_state_id} "
                    "must not be measured after snapshot capture"
                )
        if self.pv_energy_timeline is not None:
            if self.pv_energy_timeline.run_id != self.run_id:
                raise ValueError(
                    "PV energy timeline run_id must match planning input snapshot run_id"
                )
            if self.pv_energy_timeline.snapshot_id != self.snapshot_id:
                raise ValueError(
                    "PV energy timeline snapshot_id must match planning input snapshot snapshot_id"
                )
        if self.household_load_forecast is not None and (
            self.household_load_forecast.run_id != self.run_id
            or self.household_load_forecast.snapshot_id != self.snapshot_id
        ):
            raise ValueError("Household load forecast lineage must match planning input")
        if (
            self.storage_mode_capability_evidence is not None
            and self.storage_mode_capability_evidence.captured_at != self.captured_at
        ):
            raise ValueError("storage mode capability evidence must share snapshot capture time")


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
class ProjectedHouseholdEnergyBalanceInterval:
    starts_at: datetime
    ends_at: datetime
    current_usable_storage_energy_wh: float
    expected_usable_pv_energy_wh: float
    planned_grid_energy_wh: float
    household_load_forecast_energy_wh: float
    known_future_demand_energy_wh: float
    conversion_losses_wh: float
    other_planned_household_energy_flows_wh: float
    projected_storage_energy_wh: float
    confidence: float
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectedHouseholdEnergyBalance:
    balance_id: str
    run_id: str
    snapshot_id: str
    storage_state_id: str
    intervals: tuple[ProjectedHouseholdEnergyBalanceInterval, ...]


@dataclass(frozen=True, slots=True)
class StorageEnergyRequirement:
    requirement_id: str
    run_id: str
    snapshot_id: str
    storage_state_id: str
    projected_balance_id: str
    required_energy_wh: float
    required_soc: float
    required_by: datetime
    reason: str
    confidence: float
    evidence_ids: tuple[str, ...]
    reserve_contribution_wh: float


@dataclass(frozen=True, slots=True)
class PlanningGap:
    kind: str
    starts_at: datetime
    ends_at: datetime
    duration_seconds: float
    assumption: str
    confidence: float


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
class PVForecastBasisInterval:
    source_interval_id: str
    starts_at: datetime
    ends_at: datetime
    selected_energy_wh: float
    confidence: float
    forecast_evidence_ids: tuple[str, ...]
    forecast_range_status: str
    forecast_range_method_version: str | None
    conversion_method_version: str | None


@dataclass(frozen=True, slots=True)
class PVForecastBasisAssumption:
    assumption_id: str
    basis: str
    scope: str
    status: str
    unavailable_reason: str | None
    intervals: tuple[PVForecastBasisInterval, ...]
    method_version: str


@dataclass(frozen=True, slots=True)
class PVForecastAssumptionSet:
    assumption_set_id: str
    run_id: str
    snapshot_id: str
    maximum_assumption_count: int
    assumptions: tuple[PVForecastBasisAssumption, ...]
    method_version: str


@dataclass(frozen=True, slots=True)
class CandidateSet:
    run_id: str
    snapshot_id: str
    candidate_set_id: str
    candidates: tuple[Candidate, ...]
    energy_paths: tuple[EnergyPath, ...]
    projected_balances: tuple[
        ProjectedHouseholdEnergyBalance,
        ...,
    ] = ()
    storage_requirements: tuple[StorageEnergyRequirement, ...] = ()
    planning_gaps: tuple[PlanningGap, ...] = ()
    pv_forecast_assumption_set: PVForecastAssumptionSet | None = None
    derivation_status: str = "not_available"
    derivation_reason: str | None = "required_inputs_missing"


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
