"""Observer-only projection of evidence-backed PV attenuation ranges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite
from typing import Any

from picot.v2.contracts import (
    PVAttenuationBucket,
    PVEnergyTimelineInterval,
    PVForecastAttenuationProfile,
)

ATTENUATED_RANGE_METHOD_VERSION = "pv-attenuated-forecast-range:v1"


@dataclass(frozen=True, slots=True)
class PVAttenuatedForecastRange:
    """Traceable side-by-side source and attenuated forecast range."""

    derivation_id: str
    installation_scope_id: str
    source_interval_id: str
    starts_at: datetime
    ends_at: datetime
    projected_at: datetime
    minutes_from_sunset: float | None
    status: str
    unavailable_reason: str | None
    observer_only: bool
    original_lower_energy_wh: float | None
    original_central_energy_wh: float | None
    original_upper_energy_wh: float | None
    corrected_lower_energy_wh: float | None
    corrected_central_energy_wh: float | None
    corrected_upper_energy_wh: float | None
    source_confidence: float
    profile_id: str | None
    bucket_id: str | None
    attenuation_factor: float
    profile_confidence: float | None
    forecast_evidence_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    rejected_observation_ids: tuple[str, ...]
    source_range_method_version: str | None
    correction_method_version: str

    def __post_init__(self) -> None:
        if self.status not in ("available", "unavailable"):
            raise ValueError("status must be available or unavailable")
        if self.status == "unavailable" and not self.unavailable_reason:
            raise ValueError("unavailable result requires unavailable_reason")
        if not self.observer_only:
            raise ValueError("attenuated range must remain observer-only")
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        for value in (self.starts_at, self.ends_at, self.projected_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("datetimes must be timezone-aware")
        if not 0.0 <= self.source_confidence <= 1.0:
            raise ValueError("source_confidence must be between 0 and 1")
        if (
            not isfinite(self.attenuation_factor)
            or not 0.0 <= self.attenuation_factor <= 1.0
        ):
            raise ValueError("attenuation_factor must be between 0 and 1")
        if self.profile_confidence is not None and not (
            0.0 <= self.profile_confidence <= 1.0
        ):
            raise ValueError("profile_confidence must be between 0 and 1")
        if not self.correction_method_version.strip():
            raise ValueError("correction_method_version must be explicit")


def _identity(
    *,
    installation_scope_id: str,
    forecast: PVEnergyTimelineInterval,
    profile_id: str | None,
    bucket_id: str | None,
    attenuation_factor: float,
    projected_at: datetime,
    minutes_from_sunset: float | None,
    status: str,
    unavailable_reason: str | None,
) -> str:
    parts = (
        installation_scope_id,
        forecast.interval_id,
        forecast.starts_at.isoformat(),
        forecast.ends_at.isoformat(),
        profile_id or "",
        bucket_id or "",
        format(attenuation_factor, ".17g"),
        projected_at.isoformat(),
        (
            format(minutes_from_sunset, ".17g")
            if minutes_from_sunset is not None
            else ""
        ),
        status,
        unavailable_reason or "",
        ATTENUATED_RANGE_METHOD_VERSION,
    )
    digest = sha256("\x1f".join(parts).encode()).hexdigest()[:16]
    return f"pv-attenuated-range-{digest}"


def _matching_bucket(
    profile: PVForecastAttenuationProfile,
    minutes_from_sunset: float,
) -> PVAttenuationBucket | None:
    return next(
        (
            bucket
            for bucket in profile.buckets
            if bucket.sunset_offset_starts_minutes
            <= minutes_from_sunset
            < bucket.sunset_offset_ends_minutes
        ),
        None,
    )


def derive_pv_attenuated_forecast_range(
    *,
    installation_scope_id: str,
    forecast: PVEnergyTimelineInterval,
    profile: PVForecastAttenuationProfile | None,
    minutes_from_sunset: float | None,
    projected_at: datetime,
) -> PVAttenuatedForecastRange:
    """Derive a visible correction without changing the source forecast."""

    if projected_at.tzinfo is None or projected_at.utcoffset() is None:
        raise ValueError("projected_at must be timezone-aware")
    if (
        minutes_from_sunset is not None
        and not isfinite(minutes_from_sunset)
    ):
        raise ValueError("minutes_from_sunset must be finite")

    range_available = (
        forecast.forecast_range_status == "available"
        and forecast.forecast_lower_energy_wh is not None
        and forecast.forecast_central_energy_wh is not None
        and forecast.forecast_upper_energy_wh is not None
    )
    original_lower = (
        forecast.forecast_lower_energy_wh if range_available else None
    )
    original_central = (
        forecast.forecast_central_energy_wh if range_available else None
    )
    original_upper = (
        forecast.forecast_upper_energy_wh if range_available else None
    )

    status = "unavailable"
    reason: str | None = None
    factor = 1.0
    profile_id = profile.profile_id if profile is not None else None
    bucket: PVAttenuationBucket | None = None

    if not range_available:
        reason = "source_range_unavailable"
    elif profile is None:
        reason = "profile_missing"
    elif profile.installation_scope_id != installation_scope_id:
        reason = "installation_scope_mismatch"
    elif profile.status != "available":
        reason = "profile_unavailable"
    elif not profile.valid_from <= projected_at < profile.valid_until:
        reason = "profile_outside_validity"
    elif minutes_from_sunset is None:
        reason = "sunset_offset_missing"
    else:
        bucket = _matching_bucket(profile, minutes_from_sunset)
        if bucket is None:
            reason = "no_matching_bucket"
        elif bucket.status != "available":
            reason = "bucket_unavailable"
        else:
            status = "available"
            factor = bucket.attenuation_factor

    corrected_lower = (
        original_lower * factor if original_lower is not None else None
    )
    corrected_central = (
        original_central * factor if original_central is not None else None
    )
    corrected_upper = (
        original_upper * factor if original_upper is not None else None
    )
    bucket_id = bucket.bucket_id if bucket is not None else None
    profile_confidence = (
        bucket.profile_confidence if bucket is not None else None
    )
    observation_ids = (
        bucket.observation_ids if bucket is not None else ()
    )
    rejected_observation_ids = (
        bucket.rejected_observation_ids if bucket is not None else ()
    )
    derivation_id = _identity(
        installation_scope_id=installation_scope_id,
        forecast=forecast,
        profile_id=profile_id,
        bucket_id=bucket_id,
        attenuation_factor=factor,
        projected_at=projected_at,
        minutes_from_sunset=minutes_from_sunset,
        status=status,
        unavailable_reason=reason,
    )

    return PVAttenuatedForecastRange(
        derivation_id=derivation_id,
        installation_scope_id=installation_scope_id,
        source_interval_id=forecast.interval_id,
        starts_at=forecast.starts_at,
        ends_at=forecast.ends_at,
        projected_at=projected_at,
        minutes_from_sunset=minutes_from_sunset,
        status=status,
        unavailable_reason=reason,
        observer_only=True,
        original_lower_energy_wh=original_lower,
        original_central_energy_wh=original_central,
        original_upper_energy_wh=original_upper,
        corrected_lower_energy_wh=corrected_lower,
        corrected_central_energy_wh=corrected_central,
        corrected_upper_energy_wh=corrected_upper,
        source_confidence=forecast.confidence,
        profile_id=profile_id,
        bucket_id=bucket_id,
        attenuation_factor=factor,
        profile_confidence=profile_confidence,
        forecast_evidence_ids=forecast.forecast_evidence_ids,
        observation_ids=observation_ids,
        rejected_observation_ids=rejected_observation_ids,
        source_range_method_version=forecast.forecast_range_method_version,
        correction_method_version=ATTENUATED_RANGE_METHOD_VERSION,
    )


def project_pv_attenuated_forecast_range(
    result: PVAttenuatedForecastRange,
) -> dict[str, Any]:
    """Expose every source, correction and lineage value independently."""

    return {
        "pv_attenuation_derivation_id": result.derivation_id,
        "pv_attenuation_installation_scope_id": (
            result.installation_scope_id
        ),
        "pv_attenuation_source_interval_id": result.source_interval_id,
        "pv_attenuation_starts_at": result.starts_at.isoformat(),
        "pv_attenuation_ends_at": result.ends_at.isoformat(),
        "pv_attenuation_projected_at": result.projected_at.isoformat(),
        "pv_attenuation_minutes_from_sunset": (
            result.minutes_from_sunset
        ),
        "pv_attenuation_status": result.status,
        "pv_attenuation_unavailable_reason": result.unavailable_reason,
        "pv_attenuation_observer_only": result.observer_only,
        "pv_attenuation_original_lower_energy_wh": (
            result.original_lower_energy_wh
        ),
        "pv_attenuation_original_central_energy_wh": (
            result.original_central_energy_wh
        ),
        "pv_attenuation_original_upper_energy_wh": (
            result.original_upper_energy_wh
        ),
        "pv_attenuation_corrected_lower_energy_wh": (
            result.corrected_lower_energy_wh
        ),
        "pv_attenuation_corrected_central_energy_wh": (
            result.corrected_central_energy_wh
        ),
        "pv_attenuation_corrected_upper_energy_wh": (
            result.corrected_upper_energy_wh
        ),
        "pv_attenuation_source_confidence": result.source_confidence,
        "pv_attenuation_profile_id": result.profile_id,
        "pv_attenuation_bucket_id": result.bucket_id,
        "pv_attenuation_factor": result.attenuation_factor,
        "pv_attenuation_profile_confidence": result.profile_confidence,
        "pv_attenuation_forecast_evidence_ids": (
            result.forecast_evidence_ids
        ),
        "pv_attenuation_observation_ids": result.observation_ids,
        "pv_attenuation_rejected_observation_ids": (
            result.rejected_observation_ids
        ),
        "pv_attenuation_source_range_method_version": (
            result.source_range_method_version
        ),
        "pv_attenuation_correction_method_version": (
            result.correction_method_version
        ),
    }
