"""Immutable contracts for the PicoT v2 canonical pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

from picot.domain.capability_snapshot import CapabilitySnapshotSet
from picot.domain.charge_source_policy import ChargeSourcePolicy
from picot.domain.energy_path import PathSegment, ProjectedEnergyState
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.v2.household_planning_regime import (
    HouseholdPlanningRegime,
    UserObjectiveProfile,
)
from picot.v2.plan_commitment_store import ActivePlanCommitment

if TYPE_CHECKING:
    from picot.v2.storage_mode_provenance import StorageModeControlProvenance
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
            raise ValueError(
                "forecast_range_status must be available or unavailable"
            )
        if self.forecast_range_status == "available":
            if self.evidence_type != "FORECAST":
                raise ValueError(
                    "available forecast range requires FORECAST evidence"
                )
            forecast_values = (
                self.forecast_lower_energy_wh,
                self.forecast_central_energy_wh,
                self.forecast_upper_energy_wh,
            )
            if any(value is None for value in forecast_values):
                raise ValueError(
                    "available forecast range requires lower, central, "
                    "and upper energy"
                )
            lower, central, upper = forecast_values
            assert lower is not None
            assert central is not None
            assert upper is not None
            if not 0.0 <= lower <= central <= upper:
                raise ValueError(
                    "forecast range must satisfy "
                    "0 <= lower <= central <= upper"
                )
            if central != self.pv_energy_wh:
                raise ValueError(
                    "forecast central energy must equal pv_energy_wh"
                )
            if not self.forecast_range_source_fields:
                raise ValueError(
                    "available forecast range requires source fields"
                )
            if not self.forecast_range_method_version:
                raise ValueError(
                    "available forecast range requires method version"
                )
        if self.evidence_type not in ("ACTUAL", "FORECAST", "MIXED"):
            raise ValueError(
                "evidence_type must be ACTUAL, FORECAST, or MIXED"
            )
        if (
            self.evidence_type == "ACTUAL"
            and not self.actual_evidence_ids
        ):
            raise ValueError(
                "ACTUAL interval requires actual evidence"
            )
        if (
            self.evidence_type == "FORECAST"
            and not self.forecast_evidence_ids
        ):
            raise ValueError(
                "FORECAST interval requires forecast evidence"
            )
        if self.evidence_type == "MIXED" and (
            not self.actual_evidence_ids
            or not self.forecast_evidence_ids
        ):
            raise ValueError(
                "MIXED interval requires actual and forecast evidence"
            )


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
                raise ValueError(
                    "intervals must be chronologically ordered"
                )
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
    solar_alignment_method_version: str = (
        "solar-alignment-unavailable"
    )

    def __post_init__(self) -> None:
        datetimes = (
            self.starts_at,
            self.ends_at,
            self.forecast_captured_at,
        )
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in datetimes
        ):
            raise ValueError(
                "observation datetimes must be timezone-aware"
            )
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
            raise ValueError(
                "forecast range must satisfy "
                "0 <= lower <= central <= upper"
            )
        if (
            not isfinite(self.actual_energy_wh)
            or self.actual_energy_wh < 0.0
        ):
            raise ValueError(
                "actual_energy_wh must not be negative"
            )
        if not 0.0 <= self.forecast_confidence <= 1.0:
            raise ValueError(
                "forecast_confidence must be between 0 and 1"
            )
        if not 0.0 <= self.actual_confidence <= 1.0:
            raise ValueError(
                "actual_confidence must be between 0 and 1"
            )
        if (
            not isfinite(self.solar_azimuth_degrees)
            or not 0.0 <= self.solar_azimuth_degrees <= 360.0
        ):
            raise ValueError(
                "solar_azimuth_degrees must be between 0 and 360"
            )
        if (
            not isfinite(self.solar_elevation_degrees)
            or not -90.0 <= self.solar_elevation_degrees <= 90.0
        ):
            raise ValueError(
                "solar_elevation_degrees must be between -90 and 90"
            )
        if not isfinite(self.minutes_from_sunset):
            raise ValueError("minutes_from_sunset must be finite")
        solar_datetimes = (self.solar_observed_at, self.sunset_at)
        if (
            self.solar_observed_at is not None
            and self.sunset_at is None
        ):
            raise ValueError(
                "solar observation requires sunset_at"
            )
        if any(
            value is not None
            and (
                value.tzinfo is None
                or value.utcoffset() is None
            )
            for value in solar_datetimes
        ):
            raise ValueError(
                "solar lineage datetimes must be timezone-aware"
            )
        if not self.solar_evidence_id.strip():
            raise ValueError("solar evidence must be explicit")
        if not self.forecast_evidence_ids:
            raise ValueError("forecast evidence must be explicit")
        if not self.actual_evidence_ids:
            raise ValueError("actual evidence must be explicit")
        if self.alignment_status not in ("aligned", "unaligned"):
            raise ValueError(
                "alignment_status must be aligned or unaligned"
            )
        if self.coverage_status not in ("complete", "partial"):
            raise ValueError(
                "coverage_status must be complete or partial"
            )
        if self.eligibility_status not in (
            "unassessed",
            "eligible",
            "rejected",
        ):
            raise ValueError(
                "eligibility_status must be unassessed, eligible, or rejected"
            )
        if (
            self.eligibility_status == "unassessed"
            and not self.eligibility_reason
        ):
            raise ValueError(
                "unassessed observation requires eligibility_reason"
            )
        if (
            self.eligibility_status == "rejected"
            and not self.eligibility_reason
        ):
            raise ValueError(
                "rejected observation requires eligibility_reason"
            )
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
            or self.sunset_offset_starts_minutes
            >= self.sunset_offset_ends_minutes
        ):
            raise ValueError(
                "sunset offset start must be before end"
            )
        if (
            not isfinite(self.attenuation_factor)
            or not 0.0 <= self.attenuation_factor <= 1.0
        ):
            raise ValueError(
                "attenuation_factor must be between 0 and 1"
            )
        if self.sample_count < 0:
            raise ValueError("sample_count must not be negative")
        if (
            self.distinct_day_count < 0
            or self.distinct_day_count > self.sample_count
        ):
            raise ValueError(
                "distinct_day_count must not exceed sample_count"
            )
        if not isfinite(self.dispersion) or self.dispersion < 0.0:
            raise ValueError("dispersion must not be negative")
        if (
            not isfinite(self.profile_confidence)
            or not 0.0 <= self.profile_confidence <= 1.0
        ):
            raise ValueError(
                "profile_confidence must be between 0 and 1"
            )
        datetimes = (
            self.evidence_starts_at,
            self.evidence_ends_at,
            self.updated_at,
        )
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in datetimes
        ):
            raise ValueError("bucket datetimes must be timezone-aware")
        if self.evidence_starts_at >= self.evidence_ends_at:
            raise ValueError(
                "evidence_starts_at must be before evidence_ends_at"
            )
        if self.status not in ("available", "unavailable"):
            raise ValueError(
                "bucket status must be available or unavailable"
            )
        if self.status == "unavailable":
            if not self.unavailable_reason:
                raise ValueError(
                    "unavailable bucket requires unavailable_reason"
                )
            if self.attenuation_factor != 1.0:
                raise ValueError(
                    "unavailable bucket must use attenuation_factor 1"
                )
        if not self.aggregation_method_version.strip():
            raise ValueError(
                "aggregation_method_version must be explicit"
            )
        if not self.configuration_version.strip():
            raise ValueError(
                "configuration_version must be explicit"
            )


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
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in datetimes
        ):
            raise ValueError("profile datetimes must be timezone-aware")
        if self.valid_from >= self.valid_until:
            raise ValueError("valid_from must be before valid_until")
        if not self.observer_only:
            raise ValueError(
                "attenuation profile must remain observer-only"
            )
        if self.status not in ("available", "unavailable"):
            raise ValueError(
                "profile status must be available or unavailable"
            )
        if self.status == "unavailable" and not self.unavailable_reason:
            raise ValueError(
                "unavailable profile requires unavailable_reason"
            )
        if self.status == "available" and not self.buckets:
            raise ValueError(
                "available profile requires attenuation buckets"
            )
        for previous, current in zip(
            self.buckets,
            self.buckets[1:],
            strict=False,
        ):
            if (
                current.sunset_offset_starts_minutes
                < previous.sunset_offset_starts_minutes
            ):
                raise ValueError(
                    "profile buckets must be chronologically ordered"
                )
            if (
                current.sunset_offset_starts_minutes
                < previous.sunset_offset_ends_minutes
            ):
                raise ValueError(
                    "profile buckets must not overlap"
                )
        if any(
            bucket.installation_scope_id
            != self.installation_scope_id
            for bucket in self.buckets
        ):
            raise ValueError(
                "bucket installation scope must match profile"
            )
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
        if self.fallback_active and not (
            self.fallback_reason and self.fallback_reason.strip()
        ):
            raise ValueError(
                "fallback_reason is required when fallback is active"
            )
        for previous, current in zip(
            self.intervals,
            self.intervals[1:],
            strict=False,
        ):
            if current.starts_at < previous.starts_at:
                raise ValueError(
                    "intervals must be chronologically ordered"
                )
            if current.starts_at < previous.ends_at:
                raise ValueError("intervals must not overlap")


@dataclass(frozen=True, slots=True)
class BMSCalibrationEvidence:
    """Fresh, explicit evidence of device-owned SOC calibration."""

    status: str
    active: bool
    observed_at: datetime | None
    source_entity_id: str | None
    evidence_id: str
    method_version: str

    def __post_init__(self) -> None:
        if self.status not in {"active", "inactive", "unavailable"}:
            raise ValueError("calibration status must be active, inactive or unavailable")
        if self.active != (self.status == "active"):
            raise ValueError("only active calibration status may set active")
        if self.observed_at is not None and (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("calibration observed_at must be timezone-aware")
        if not self.evidence_id.strip():
            raise ValueError("calibration evidence_id must be explicit")
        if not self.method_version.strip():
            raise ValueError("calibration method_version must be explicit")


@dataclass(frozen=True, slots=True)
class StoragePhysicalLimits:
    """Configured physical limits carried passively in Planning Input."""

    execution_scope_id: str
    capability_id: str
    minimum_soc: float
    maximum_soc: float
    maximum_charge_input_power_w: float
    maximum_discharge_output_power_w: float
    evidence_ids: tuple[str, ...]
    method_version: str

    def __post_init__(self) -> None:
        if not self.execution_scope_id.strip() or not self.capability_id.strip():
            raise ValueError("storage physical limit scope must be explicit")
        if not 0.0 <= self.minimum_soc <= self.maximum_soc <= 1.0:
            raise ValueError("storage physical SOC limits must be ordered")
        if self.maximum_charge_input_power_w <= 0.0:
            raise ValueError("maximum charge input power must be positive")
        if self.maximum_discharge_output_power_w <= 0.0:
            raise ValueError("maximum discharge output power must be positive")
        if not self.evidence_ids:
            raise ValueError("storage physical limit evidence must be explicit")
        if not self.method_version.strip():
            raise ValueError("storage physical limit method must be explicit")


@dataclass(frozen=True, slots=True)
class StorageRoundTripEfficiencyEvidence:
    status: str
    round_trip_efficiency: float | None
    observed_at: datetime | None
    source_entity_id: str | None
    evidence_id: str
    method_version: str

    def __post_init__(self) -> None:
        if self.status not in {"available", "unavailable"}:
            raise ValueError("storage RTE status must be available or unavailable")
        if self.status == "available":
            if (
                self.round_trip_efficiency is None
                or not 0.5 <= self.round_trip_efficiency <= 1.0
                or self.observed_at is None
                or self.source_entity_id is None
            ):
                raise ValueError("available storage RTE evidence must be complete")
        elif self.round_trip_efficiency is not None:
            raise ValueError("unavailable storage RTE must not carry a value")
        if not self.evidence_id.strip() or not self.method_version.strip():
            raise ValueError("storage RTE evidence lineage must be explicit")


@dataclass(frozen=True, slots=True)
class PlanningInputSnapshot:
    run_id: str
    snapshot_id: str
    captured_at: datetime
    picot_version: str
    architecture_baseline_commit: str
    pipeline_contract_version: int
    strategy_id: str
    user_objective_profile: UserObjectiveProfile | None = None
    household_planning_regime: HouseholdPlanningRegime | None = None
    horizon_end: datetime | None = None
    price_points: tuple[PriceForecastPoint, ...] = ()
    current_storage_states: tuple[CurrentStorageState, ...] = ()
    pv_energy_timeline: PVEnergyTimeline | None = None
    household_load_forecast: HouseholdLoadForecast | None = None
    storage_mode_capability_evidence: ZendureModeCapabilityEvidence | None = None
    storage_mode_control_provenance: StorageModeControlProvenance | None = None
    bms_calibration_evidence: BMSCalibrationEvidence | None = None
    capability_snapshot_set: CapabilitySnapshotSet | None = None
    storage_physical_limits: tuple[StoragePhysicalLimits, ...] = ()
    storage_round_trip_efficiency: StorageRoundTripEfficiencyEvidence | None = None
    active_plan_commitments: tuple[ActivePlanCommitment, ...] = ()

    def __post_init__(self) -> None:
        scope_ids = tuple(
            item.execution_scope_id for item in self.active_plan_commitments
        )
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("only one active plan commitment is allowed per scope")
        if any(
            item.ends_at <= self.captured_at
            for item in self.active_plan_commitments
        ):
            raise ValueError("expired plan commitments may not enter Planning Input")
        for state in self.current_storage_states:
            if state.measured_at > self.captured_at:
                raise ValueError(
                    f"current storage state {state.storage_state_id} "
                    "must not be measured after snapshot capture"
                )
        if self.pv_energy_timeline is not None:
            if self.pv_energy_timeline.run_id != self.run_id:
                raise ValueError(
                    "PV energy timeline run_id must match "
                    "planning input snapshot run_id"
                )
            if self.pv_energy_timeline.snapshot_id != self.snapshot_id:
                raise ValueError(
                    "PV energy timeline snapshot_id must match "
                    "planning input snapshot snapshot_id"
                )
        if self.household_load_forecast is not None and (
            self.household_load_forecast.run_id != self.run_id
            or self.household_load_forecast.snapshot_id != self.snapshot_id
        ):
            raise ValueError(
                "Household load forecast lineage must match planning input"
            )
        if (
            self.storage_mode_capability_evidence is not None
            and self.storage_mode_capability_evidence.captured_at
            != self.captured_at
        ):
            raise ValueError(
                "storage mode capability evidence must share snapshot capture time"
            )
        if self.capability_snapshot_set is not None and (
            self.capability_snapshot_set.snapshot_id != self.snapshot_id
            or self.capability_snapshot_set.captured_at != self.captured_at
        ):
            raise ValueError(
                "capability snapshot set lineage must match planning input"
            )
        physical_limit_scopes = tuple(
            (item.execution_scope_id, item.capability_id)
            for item in self.storage_physical_limits
        )
        if len(physical_limit_scopes) != len(set(physical_limit_scopes)):
            raise ValueError("storage physical limits must be unique per capability")


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
    storage_confidence: float | None = None
    pv_confidence: float | None = None
    load_confidence: float | None = None
    confidence_method_version: str | None = None


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
    confidence_method_version: str = (
        "legacy-storage-requirement-confidence:unversioned"
    )
    requirement_kind: str = "household_energy"
    satisfaction_mode: str = "available_at"

    def __post_init__(self) -> None:
        if self.requirement_kind not in {
            "household_energy",
            "daily_storage_target",
        }:
            raise ValueError("Storage requirement kind is unsupported")
        if self.satisfaction_mode not in {"available_at", "reached_by"}:
            raise ValueError("Storage requirement satisfaction mode is unsupported")
        if (
            self.requirement_kind == "daily_storage_target"
            and self.satisfaction_mode != "reached_by"
        ):
            raise ValueError("Daily storage targets must use reached_by semantics")


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
    segments: tuple[PathSegment, ...] = ()
    projected_states: tuple[ProjectedEnergyState, ...] = ()
    capability_confidence: float | None = None

    def __post_init__(self) -> None:
        if self.segment_ids != tuple(segment.segment_id for segment in self.segments):
            raise ValueError("energy path segment IDs must match timed segments")
        if any(
            left.at >= right.at
            for left, right in zip(
                self.projected_states,
                self.projected_states[1:],
                strict=False,
            )
        ):
            raise ValueError("projected states must be chronologically ordered")


@dataclass(frozen=True, slots=True)
class Candidate:
    run_id: str
    snapshot_id: str
    candidate_id: str
    energy_path_id: str
    family: str
    pv_forecast_basis: str = "central"


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
class ConfidenceComponent:
    name: str
    value: float
    method_version: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.method_version.strip():
            raise ValueError("confidence component identity must be explicit")
        if not 0.0 <= self.value <= 1.0:
            raise ValueError("confidence component must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    result: float
    limiting_component: str
    method_version: str
    components: tuple[ConfidenceComponent, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.result <= 1.0:
            raise ValueError("confidence result must be between 0 and 1")
        if not self.limiting_component.strip() or not self.method_version.strip():
            raise ValueError("confidence assessment identity must be explicit")
        names = tuple(item.name for item in self.components)
        if self.limiting_component not in names:
            raise ValueError("limiting confidence component must be present")
        if len(names) != len(set(names)):
            raise ValueError("confidence component names must be unique")


@dataclass(frozen=True, slots=True)
class DelegatedStorageCandidateOutcome:
    outcome_id: str
    run_id: str
    snapshot_id: str
    candidate_id: str
    energy_path_id: str
    storage_requirement_id: str
    capability_ids: tuple[str, ...]
    charge_window_starts_at: datetime
    charge_window_ends_at: datetime
    storage_energy_at_window_end_wh: float
    storage_energy_at_requirement_wh: float
    required_energy_wh: float
    pv_storage_contribution_wh: float
    grid_storage_contribution_wh: float
    conversion_losses_wh: float
    requirement_satisfied: bool
    recoverability: float
    confidence: float
    evidence_ids: tuple[str, ...]
    method_version: str
    confidence_assessment: ConfidenceAssessment | None = None
    pv_forecast_basis: str = "central"
    storage_energy_at_window_start_wh: float | None = None
    projected_storage_use_before_window_wh: float | None = None
    required_storage_addition_wh: float | None = None
    charge_target_satisfied: bool | None = None
    reserve_satisfied: bool | None = None
    reserve_energy_required_wh: float | None = None

    def __post_init__(self) -> None:
        if self.charge_window_starts_at >= self.charge_window_ends_at:
            raise ValueError("charge window start must be before end")
        for value in (
            self.storage_energy_at_window_end_wh,
            self.storage_energy_at_requirement_wh,
            self.required_energy_wh,
            self.pv_storage_contribution_wh,
            self.grid_storage_contribution_wh,
            self.conversion_losses_wh,
        ):
            if value < 0.0 or not isfinite(value):
                raise ValueError("Candidate Outcome energy must be finite and non-negative")
        for value, label in (
            (self.recoverability, "recoverability"),
            (self.confidence, "confidence"),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"Candidate Outcome {label} must be between 0 and 1")
        legacy_requirement_satisfied = (
            self.storage_energy_at_requirement_wh + 1e-6
            >= self.required_energy_wh
        )
        separated_requirement_satisfied = (
            self.charge_target_satisfied is True
            and self.reserve_satisfied is True
        )
        expected_requirement_satisfied = (
            separated_requirement_satisfied
            if self.charge_target_satisfied is not None
            and self.reserve_satisfied is not None
            else legacy_requirement_satisfied
        )
        if self.requirement_satisfied != expected_requirement_satisfied:
            raise ValueError("requirement satisfaction must match projected storage energy")
        if self.charge_target_satisfied is not None and (
            self.charge_target_satisfied
            != (self.storage_energy_at_window_end_wh + 1e-6 >= self.required_energy_wh)
        ):
            raise ValueError("charge target satisfaction must match window-end energy")
        if self.reserve_satisfied is not None:
            if self.reserve_energy_required_wh is None:
                raise ValueError("reserve requirement must be explicit")
            if self.reserve_satisfied != (
                self.storage_energy_at_requirement_wh + 1e-6
                >= self.reserve_energy_required_wh
            ):
                raise ValueError("reserve satisfaction must match requirement-time energy")
        for values, label in (
            (self.capability_ids, "capability"),
            (self.evidence_ids, "evidence"),
        ):
            if not values or any(not value.strip() for value in values):
                raise ValueError(f"Candidate Outcome {label} IDs must be explicit")
            if len(values) != len(set(values)):
                raise ValueError(f"Candidate Outcome {label} IDs must be unique")
        if not self.method_version.strip():
            raise ValueError("Candidate Outcome method version must be explicit")


@dataclass(frozen=True, slots=True)
class MepCandidateOutcome:
    """Diagnostic projection of one ADR-032-comparable MEP outcome."""

    outcome_id: str
    run_id: str
    snapshot_id: str
    candidate_id: str
    energy_path_id: str
    comparison_horizon_start: datetime
    comparison_horizon_end: datetime
    incumbent: bool
    validity: str
    invalidity_reasons: tuple[str, ...]
    worst_case_financial_result_eur: float | None
    self_consumed_pv_wh: float | None
    reserve_availability_wh: float | None
    confidence: float
    recoverability: float | None
    execution_complexity: int
    expected_switching_count: int | None
    evidence_ids: tuple[str, ...]
    method_version: str
    financial_equivalence_margin_eur: float
    explicit_charge_window_starts_at: datetime | None
    explicit_charge_window_ends_at: datetime | None
    target_storage_energy_wh: float
    daily_target_required_by: datetime
    daily_target_reached: bool
    daily_target_reached_at: datetime | None
    household_reserve_respected: bool

    def __post_init__(self) -> None:
        if self.comparison_horizon_end <= self.comparison_horizon_start:
            raise ValueError("MEP comparison horizon must be positive")
        if self.validity not in {"valid", "invalid"}:
            raise ValueError("MEP outcome validity must be valid or invalid")
        if self.validity == "invalid" and not self.invalidity_reasons:
            raise ValueError("Invalid MEP outcomes require reasons")
        if self.validity == "valid" and self.invalidity_reasons:
            raise ValueError("Valid MEP outcomes may not carry invalidity reasons")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("MEP outcome confidence must be bounded")
        if self.recoverability is not None and not 0.0 <= self.recoverability <= 1.0:
            raise ValueError("MEP outcome recoverability must be bounded")
        if self.execution_complexity < 0:
            raise ValueError("MEP outcome complexity must be non-negative")
        if self.expected_switching_count is not None and self.expected_switching_count < 0:
            raise ValueError("MEP outcome switching count must be non-negative")
        if self.financial_equivalence_margin_eur < 0.0:
            raise ValueError("MEP financial equivalence margin must be non-negative")
        if (self.explicit_charge_window_starts_at is None) != (
            self.explicit_charge_window_ends_at is None
        ):
            raise ValueError("MEP explicit charge window must be complete")
        if (
            self.explicit_charge_window_starts_at is not None
            and self.explicit_charge_window_ends_at is not None
            and self.explicit_charge_window_ends_at
            <= self.explicit_charge_window_starts_at
        ):
            raise ValueError("MEP explicit charge window must be positive")
        if self.target_storage_energy_wh <= 0.0:
            raise ValueError("MEP target storage energy must be positive")
        if (
            self.daily_target_required_by.tzinfo is None
            or self.daily_target_required_by.utcoffset() is None
        ):
            raise ValueError("MEP daily target deadline must be timezone-aware")
        if self.daily_target_reached != (self.daily_target_reached_at is not None):
            raise ValueError("MEP daily target result must reconcile with its time")
        if (
            self.daily_target_reached_at is not None
            and self.daily_target_reached_at > self.daily_target_required_by
        ):
            raise ValueError("MEP daily target cannot be reached after its deadline")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("MEP outcome evidence IDs must be explicit")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("MEP outcome evidence IDs must be unique")
        if not self.method_version.strip():
            raise ValueError("MEP outcome method version must be explicit")

    @property
    def charge_window_starts_at(self) -> datetime:
        return self.explicit_charge_window_starts_at or self.comparison_horizon_start

    @property
    def charge_window_ends_at(self) -> datetime:
        return self.explicit_charge_window_ends_at or self.comparison_horizon_end

    @property
    def requirement_satisfied(self) -> None:
        return None

    @property
    def storage_energy_at_requirement_wh(self) -> None:
        return None

    @property
    def storage_energy_at_window_start_wh(self) -> None:
        return None

    @property
    def storage_energy_at_window_end_wh(self) -> None:
        return None

    @property
    def required_energy_wh(self) -> float:
        return self.target_storage_energy_wh

    @property
    def required_storage_addition_wh(self) -> None:
        return None

    @property
    def projected_storage_use_before_window_wh(self) -> None:
        return None

    @property
    def pv_storage_contribution_wh(self) -> None:
        return None

    @property
    def grid_storage_contribution_wh(self) -> None:
        return None

    @property
    def conversion_losses_wh(self) -> None:
        return None

    @property
    def charge_target_satisfied(self) -> None:
        return None

    @property
    def reserve_satisfied(self) -> None:
        return None

    @property
    def reserve_energy_required_wh(self) -> None:
        return None

    @property
    def confidence_assessment(self) -> None:
        return None

    @property
    def pv_forecast_basis(self) -> str:
        return "lower-central-upper"


@dataclass(frozen=True, slots=True)
class CandidateOutcomeSet:
    run_id: str
    snapshot_id: str
    candidate_set_id: str
    outcome_set_id: str
    candidate_ids: tuple[str, ...]
    outcomes: tuple[DelegatedStorageCandidateOutcome | MepCandidateOutcome, ...] = ()

    def __post_init__(self) -> None:
        if self.outcomes and self.candidate_ids != tuple(
            outcome.candidate_id for outcome in self.outcomes
        ):
            raise ValueError("Candidate Outcome IDs must match detailed outcomes")


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    run_id: str
    snapshot_id: str
    evaluation_id: str
    candidate_set_id: str
    winning_candidate_id: str | None
    winning_energy_path_id: str | None
    reason: str
    status: str = "winner_selected"
    evaluated_candidate_ids: tuple[str, ...] = ()
    decisive_step: str | None = None
    incumbent_candidate_id: str | None = None
    financial_equivalence_margin_eur: float = 0.0
    commitment_decision: str | None = None


@dataclass(frozen=True, slots=True)
class ObserverExecutionPlanSegment:
    segment_id: str
    source_path_segment_id: str
    order: int
    starts_at: datetime
    ends_at: datetime
    primitive: ExecutionPrimitive
    capability_id: str
    purpose: str
    evidence_ids: tuple[str, ...]
    requested_power_w: float | None
    charge_source_policy: ChargeSourcePolicy | None
    planned_vendor_mode: str | None = None


@dataclass(frozen=True, slots=True)
class ObserverExecutionPlan:
    plan_id: str
    evaluation_id: str
    winning_candidate_id: str
    winning_energy_path_id: str
    execution_scope_id: str
    valid_from: datetime
    valid_until: datetime
    planned_primitive: ExecutionPrimitive
    planned_vendor_mode: str | None
    lifecycle_status: str
    observer_only: bool
    segments: tuple[ObserverExecutionPlanSegment, ...]


@dataclass(frozen=True, slots=True)
class ExecutionPlanSet:
    run_id: str
    snapshot_id: str
    plan_set_id: str
    evaluation_id: str
    winning_energy_path_id: str | None
    plan_ids: tuple[str, ...] = ()
    plans: tuple[ObserverExecutionPlan, ...] = ()

    def __post_init__(self) -> None:
        if self.plan_ids != tuple(plan.plan_id for plan in self.plans):
            raise ValueError("Execution Plan IDs must match detailed plans")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    run_id: str
    snapshot_id: str
    execution_record_id: str
    plan_set_id: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class PVChargeProgressEvidence:
    """Auditable decision basis for deferring residual grid charging."""

    method_version: str
    decision: str
    reason: str
    remaining_target_energy_wh: float | None = None
    conservative_pv_to_storage_wh: float | None = None
    required_grid_input_energy_wh: float | None = None
    acquisition_deadline: datetime | None = None
    latest_safe_grid_charge_starts_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.method_version.strip() or not self.decision.strip() or not self.reason.strip():
            raise ValueError("PV charge progress identity fields cannot be blank")
        for energy_value in (
            self.remaining_target_energy_wh,
            self.conservative_pv_to_storage_wh,
            self.required_grid_input_energy_wh,
        ):
            if energy_value is not None and energy_value < 0.0:
                raise ValueError("PV charge progress energy values cannot be negative")
        for timestamp_value in (
            self.acquisition_deadline,
            self.latest_safe_grid_charge_starts_at,
        ):
            if timestamp_value is not None and timestamp_value.tzinfo is None:
                raise ValueError("PV charge progress timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExecutionPrimitiveBoundary:
    run_id: str
    snapshot_id: str
    request_id: str | None
    execution_record_id: str
    status: str
    planned_primitive: ExecutionPrimitive | None = None
    mapping_status: str = "not_assessed"
    source_entity_id: str | None = None
    current_vendor_mode: str | None = None
    planned_vendor_mode: str | None = None
    mapping_method_version: str | None = None
    blockers: tuple[str, ...] = ()
    pv_charge_progress: PVChargeProgressEvidence | None = None


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
    dispatch_intent_id: str | None = None
    target_entity_id: str | None = None
    planned_vendor_mode: str | None = None
    failure_reason: str | None = None


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
