"""Deterministic observer-only aggregation for V2ADR-049."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from math import floor, isfinite
from statistics import median

from picot.v2.contracts import (
    PVAttenuationBucket,
    PVAttenuationObservation,
    PVForecastAttenuationProfile,
)

AGGREGATION_METHOD_VERSION = "pv-attenuation-bucket-median-mad:v1"
PROFILE_METHOD_VERSION = "pv-attenuation-profile:v1"


@dataclass(frozen=True, slots=True)
class PVAttenuationAggregationConfig:
    sunset_bucket_width_minutes: float
    minimum_sample_count: int
    minimum_distinct_days: int
    maximum_dispersion: float
    minimum_profile_confidence: float
    maximum_evidence_age_days: int
    profile_validity_days: int
    configuration_version: str

    def __post_init__(self) -> None:
        if (
            not isfinite(self.sunset_bucket_width_minutes)
            or self.sunset_bucket_width_minutes <= 0.0
        ):
            raise ValueError(
                "sunset_bucket_width_minutes must be finite and positive"
            )
        if self.minimum_sample_count <= 0:
            raise ValueError("minimum_sample_count must be positive")
        if self.minimum_distinct_days <= 0:
            raise ValueError("minimum_distinct_days must be positive")
        if self.minimum_distinct_days > self.minimum_sample_count:
            raise ValueError(
                "minimum_distinct_days must not exceed minimum_sample_count"
            )
        if (
            not isfinite(self.maximum_dispersion)
            or self.maximum_dispersion <= 0.0
        ):
            raise ValueError(
                "maximum_dispersion must be finite and positive"
            )
        if (
            not isfinite(self.minimum_profile_confidence)
            or not 0.0 <= self.minimum_profile_confidence <= 1.0
        ):
            raise ValueError(
                "minimum_profile_confidence must be between 0 and 1"
            )
        if self.maximum_evidence_age_days <= 0:
            raise ValueError(
                "maximum_evidence_age_days must be positive"
            )
        if self.profile_validity_days <= 0:
            raise ValueError("profile_validity_days must be positive")
        if not self.configuration_version.strip():
            raise ValueError("configuration_version must be explicit")


def aggregate_pv_attenuation_profile(
    *,
    installation_scope_id: str,
    observations: tuple[PVAttenuationObservation, ...],
    evaluated_at: datetime,
    config: PVAttenuationAggregationConfig,
) -> PVForecastAttenuationProfile:
    """Aggregate classified observations without applying the result."""
    if not installation_scope_id.strip():
        raise ValueError("installation_scope_id must be explicit")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    classified = tuple(
        observation
        for observation in observations
        if observation.installation_scope_id == installation_scope_id
        and observation.eligibility_status in ("eligible", "rejected")
    )
    valid_until = evaluated_at + timedelta(
        days=config.profile_validity_days
    )
    method_version = (
        f"{PROFILE_METHOD_VERSION}:{config.configuration_version}"
    )
    if not classified:
        profile_id = _profile_id(
            installation_scope_id=installation_scope_id,
            evaluated_at=evaluated_at,
            bucket_ids=(),
            configuration_version=config.configuration_version,
        )
        return PVForecastAttenuationProfile(
            profile_id=profile_id,
            installation_scope_id=installation_scope_id,
            status="unavailable",
            unavailable_reason="no_classified_observations",
            valid_from=evaluated_at,
            valid_until=valid_until,
            updated_at=evaluated_at,
            observer_only=True,
            buckets=(),
            method_version=method_version,
        )

    groups: dict[float, list[PVAttenuationObservation]] = {}
    width = config.sunset_bucket_width_minutes
    for observation in classified:
        bucket_start = floor(
            observation.minutes_from_sunset / width
        ) * width
        groups.setdefault(bucket_start, []).append(observation)

    buckets = tuple(
        _aggregate_bucket(
            installation_scope_id=installation_scope_id,
            bucket_start=bucket_start,
            observations=tuple(groups[bucket_start]),
            evaluated_at=evaluated_at,
            config=config,
        )
        for bucket_start in sorted(groups)
    )
    available = any(bucket.status == "available" for bucket in buckets)
    profile_id = _profile_id(
        installation_scope_id=installation_scope_id,
        evaluated_at=evaluated_at,
        bucket_ids=tuple(bucket.bucket_id for bucket in buckets),
        configuration_version=config.configuration_version,
    )
    return PVForecastAttenuationProfile(
        profile_id=profile_id,
        installation_scope_id=installation_scope_id,
        status="available" if available else "unavailable",
        unavailable_reason=None if available else "no_available_buckets",
        valid_from=min(
            observation.starts_at for observation in classified
        ),
        valid_until=valid_until,
        updated_at=evaluated_at,
        observer_only=True,
        buckets=buckets,
        method_version=method_version,
    )


def _aggregate_bucket(
    *,
    installation_scope_id: str,
    bucket_start: float,
    observations: tuple[PVAttenuationObservation, ...],
    evaluated_at: datetime,
    config: PVAttenuationAggregationConfig,
) -> PVAttenuationBucket:
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.starts_at,
                item.observation_id,
            ),
        )
    )
    eligible = tuple(
        item
        for item in ordered
        if item.eligibility_status == "eligible"
    )
    rejected = tuple(
        item
        for item in ordered
        if item.eligibility_status == "rejected"
    )
    ratios = tuple(
        min(
            1.0,
            item.actual_energy_wh
            / item.forecast_central_energy_wh,
        )
        for item in eligible
    )
    sample_count = len(eligible)
    distinct_day_count = len(
        {item.starts_at.date() for item in eligible}
    )
    central_ratio = median(ratios) if ratios else 1.0
    dispersion = (
        median(tuple(abs(value - central_ratio) for value in ratios))
        if ratios
        else 0.0
    )
    newest_evidence_at = max(item.ends_at for item in ordered)
    stale = (
        evaluated_at - newest_evidence_at
    ).total_seconds() > (
        config.maximum_evidence_age_days * 24 * 60 * 60
    )

    status = "available"
    unavailable_reason: str | None = None
    factor = central_ratio
    profile_confidence = _profile_confidence(
        eligible=eligible,
        dispersion=dispersion,
        config=config,
    )
    if stale:
        status = "unavailable"
        unavailable_reason = "stale_profile"
    elif (
        sample_count < config.minimum_sample_count
        or distinct_day_count < config.minimum_distinct_days
    ):
        status = "unavailable"
        unavailable_reason = "insufficient_structural_evidence"
    elif dispersion > config.maximum_dispersion:
        status = "unavailable"
        unavailable_reason = "conflicting_evidence"
    elif profile_confidence < config.minimum_profile_confidence:
        status = "unavailable"
        unavailable_reason = "profile_confidence_below_minimum"

    if status == "unavailable":
        factor = 1.0
        if unavailable_reason != "profile_confidence_below_minimum":
            profile_confidence = 0.0

    bucket_end = bucket_start + config.sunset_bucket_width_minutes
    observation_ids = tuple(item.observation_id for item in eligible)
    rejected_ids = tuple(item.observation_id for item in rejected)
    bucket_id = _bucket_id(
        installation_scope_id=installation_scope_id,
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        observation_ids=observation_ids,
        rejected_observation_ids=rejected_ids,
        configuration_version=config.configuration_version,
    )
    return PVAttenuationBucket(
        bucket_id=bucket_id,
        installation_scope_id=installation_scope_id,
        sunset_offset_starts_minutes=bucket_start,
        sunset_offset_ends_minutes=bucket_end,
        attenuation_factor=factor,
        status=status,
        unavailable_reason=unavailable_reason,
        sample_count=sample_count,
        distinct_day_count=distinct_day_count,
        dispersion=dispersion,
        profile_confidence=profile_confidence,
        evidence_starts_at=min(item.starts_at for item in ordered),
        evidence_ends_at=max(item.ends_at for item in ordered),
        updated_at=evaluated_at,
        observation_ids=observation_ids,
        rejected_observation_ids=rejected_ids,
        aggregation_method_version=AGGREGATION_METHOD_VERSION,
        configuration_version=config.configuration_version,
    )


def _profile_confidence(
    *,
    eligible: tuple[PVAttenuationObservation, ...],
    dispersion: float,
    config: PVAttenuationAggregationConfig,
) -> float:
    if not eligible:
        return 0.0
    forecast_confidence = median(
        tuple(item.forecast_confidence for item in eligible)
    )
    actual_confidence = median(
        tuple(item.actual_confidence for item in eligible)
    )
    sample_score = min(
        len(eligible) / config.minimum_sample_count,
        1.0,
    )
    day_score = min(
        len({item.starts_at.date() for item in eligible})
        / config.minimum_distinct_days,
        1.0,
    )
    dispersion_score = max(
        0.0,
        1.0 - dispersion / config.maximum_dispersion,
    )
    return min(
        forecast_confidence,
        actual_confidence,
        sample_score,
        day_score,
        dispersion_score,
    )


def _bucket_id(
    *,
    installation_scope_id: str,
    bucket_start: float,
    bucket_end: float,
    observation_ids: tuple[str, ...],
    rejected_observation_ids: tuple[str, ...],
    configuration_version: str,
) -> str:
    seed = "|".join(
        (
            installation_scope_id,
            str(bucket_start),
            str(bucket_end),
            *observation_ids,
            *rejected_observation_ids,
            configuration_version,
            AGGREGATION_METHOD_VERSION,
        )
    )
    return (
        "pv-attenuation-bucket-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )


def _profile_id(
    *,
    installation_scope_id: str,
    evaluated_at: datetime,
    bucket_ids: tuple[str, ...],
    configuration_version: str,
) -> str:
    seed = "|".join(
        (
            installation_scope_id,
            evaluated_at.isoformat(),
            *bucket_ids,
            configuration_version,
            PROFILE_METHOD_VERSION,
        )
    )
    return (
        "pv-attenuation-profile-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )
