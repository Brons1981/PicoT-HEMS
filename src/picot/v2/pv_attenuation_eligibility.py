"""Deterministic observer-only eligibility for V2ADR-049 evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite

from picot.v2.contracts import PVAttenuationObservation

ELIGIBILITY_METHOD_VERSION = "pv-attenuation-eligibility:v1"


@dataclass(frozen=True, slots=True)
class PVAttenuationEligibilityConfig:
    minimum_forecast_energy_wh: float
    minimum_forecast_confidence: float
    minimum_actual_confidence: float
    maximum_attenuation_ratio: float
    minimum_preceding_tracking_ratio: float
    maximum_preceding_tracking_ratio: float
    minimum_distinct_days: int
    sunset_bucket_tolerance_minutes: float
    maximum_evidence_age_days: int
    configuration_version: str

    def __post_init__(self) -> None:
        if (
            not isfinite(self.minimum_forecast_energy_wh)
            or self.minimum_forecast_energy_wh <= 0.0
        ):
            raise ValueError(
                "minimum_forecast_energy_wh must be finite and positive"
            )
        for name, value in (
            (
                "minimum_forecast_confidence",
                self.minimum_forecast_confidence,
            ),
            ("minimum_actual_confidence", self.minimum_actual_confidence),
            ("maximum_attenuation_ratio", self.maximum_attenuation_ratio),
            (
                "minimum_preceding_tracking_ratio",
                self.minimum_preceding_tracking_ratio,
            ),
            (
                "maximum_preceding_tracking_ratio",
                self.maximum_preceding_tracking_ratio,
            ),
        ):
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if (
            self.minimum_preceding_tracking_ratio
            > self.maximum_preceding_tracking_ratio
        ):
            raise ValueError(
                "preceding tracking ratio bounds must be ordered"
            )
        if self.minimum_distinct_days < 2:
            raise ValueError("minimum_distinct_days must be at least 2")
        if (
            not isfinite(self.sunset_bucket_tolerance_minutes)
            or self.sunset_bucket_tolerance_minutes < 0.0
        ):
            raise ValueError(
                "sunset_bucket_tolerance_minutes must not be negative"
            )
        if self.maximum_evidence_age_days <= 0:
            raise ValueError(
                "maximum_evidence_age_days must be positive"
            )
        if not self.configuration_version.strip():
            raise ValueError("configuration_version must be explicit")


def classify_pv_attenuation_observation(
    *,
    target_observation_id: str,
    observations: tuple[PVAttenuationObservation, ...],
    evaluated_at: datetime,
    config: PVAttenuationEligibilityConfig,
) -> PVAttenuationObservation:
    """Classify one retained observation with a fixed rejection priority."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    target = next(
        (
            observation
            for observation in observations
            if observation.observation_id == target_observation_id
        ),
        None,
    )
    if target is None:
        raise ValueError("target observation must exist")

    method_version = (
        f"{ELIGIBILITY_METHOD_VERSION}:{config.configuration_version}"
    )
    reason = _target_quality_rejection(target, evaluated_at, config)
    if reason is None and not _preceding_forecast_was_tracked(
        target,
        observations,
        config,
    ):
        reason = "forecast_not_tracked_before_window"
    if reason is None and not _attenuation_is_continuous(
        target,
        observations,
        config,
    ):
        reason = "attenuation_not_continuous"
    if reason is None and not _has_distinct_day_recurrence(
        target,
        observations,
        evaluated_at,
        config,
    ):
        reason = "insufficient_distinct_day_recurrence"

    if reason is not None:
        return replace(
            target,
            eligibility_status="rejected",
            eligibility_reason=reason,
            eligibility_method_version=method_version,
        )
    return replace(
        target,
        eligibility_status="eligible",
        eligibility_reason=None,
        eligibility_method_version=method_version,
    )


def _target_quality_rejection(
    observation: PVAttenuationObservation,
    evaluated_at: datetime,
    config: PVAttenuationEligibilityConfig,
) -> str | None:
    if observation.alignment_status != "aligned":
        return "interval_unaligned"
    if observation.coverage_status != "complete":
        return "actual_coverage_incomplete"
    if (
        observation.forecast_central_energy_wh
        < config.minimum_forecast_energy_wh
    ):
        return "forecast_below_energy_floor"
    if (
        observation.forecast_confidence
        < config.minimum_forecast_confidence
    ):
        return "forecast_confidence_below_minimum"
    if observation.actual_confidence < config.minimum_actual_confidence:
        return "actual_confidence_below_minimum"
    age = evaluated_at - observation.ends_at
    if age.total_seconds() < 0:
        return "evidence_from_future"
    if age.total_seconds() > (
        config.maximum_evidence_age_days * 24 * 60 * 60
    ):
        return "evidence_stale"
    if (
        _actual_to_forecast_ratio(observation)
        > config.maximum_attenuation_ratio
    ):
        return "no_attenuation_signal"
    return None


def _preceding_forecast_was_tracked(
    target: PVAttenuationObservation,
    observations: tuple[PVAttenuationObservation, ...],
    config: PVAttenuationEligibilityConfig,
) -> bool:
    preceding = next(
        (
            observation
            for observation in observations
            if observation.installation_scope_id
            == target.installation_scope_id
            and observation.ends_at == target.starts_at
        ),
        None,
    )
    if preceding is None:
        return False
    ratio = _actual_to_forecast_ratio(preceding)
    return (
        preceding.alignment_status == "aligned"
        and preceding.coverage_status == "complete"
        and preceding.forecast_central_energy_wh
        >= config.minimum_forecast_energy_wh
        and preceding.forecast_confidence
        >= config.minimum_forecast_confidence
        and preceding.actual_confidence
        >= config.minimum_actual_confidence
        and config.minimum_preceding_tracking_ratio
        <= ratio
        <= config.maximum_preceding_tracking_ratio
    )


def _attenuation_is_continuous(
    target: PVAttenuationObservation,
    observations: tuple[PVAttenuationObservation, ...],
    config: PVAttenuationEligibilityConfig,
) -> bool:
    following = next(
        (
            observation
            for observation in observations
            if observation.installation_scope_id
            == target.installation_scope_id
            and observation.starts_at == target.ends_at
        ),
        None,
    )
    return (
        following is not None
        and following.alignment_status == "aligned"
        and following.coverage_status == "complete"
        and following.forecast_central_energy_wh
        >= config.minimum_forecast_energy_wh
        and following.forecast_confidence
        >= config.minimum_forecast_confidence
        and following.actual_confidence
        >= config.minimum_actual_confidence
        and _actual_to_forecast_ratio(following)
        <= config.maximum_attenuation_ratio
    )


def _has_distinct_day_recurrence(
    target: PVAttenuationObservation,
    observations: tuple[PVAttenuationObservation, ...],
    evaluated_at: datetime,
    config: PVAttenuationEligibilityConfig,
) -> bool:
    qualifying_days = {
        observation.starts_at.date()
        for observation in observations
        if observation.installation_scope_id
        == target.installation_scope_id
        and abs(
            observation.minutes_from_sunset
            - target.minutes_from_sunset
        )
        <= config.sunset_bucket_tolerance_minutes
        and _recurrence_observation_qualifies(
            observation,
            evaluated_at,
            config,
        )
    }
    return len(qualifying_days) >= config.minimum_distinct_days


def _recurrence_observation_qualifies(
    observation: PVAttenuationObservation,
    evaluated_at: datetime,
    config: PVAttenuationEligibilityConfig,
) -> bool:
    return _target_quality_rejection(
        observation,
        evaluated_at,
        config,
    ) is None


def _actual_to_forecast_ratio(
    observation: PVAttenuationObservation,
) -> float:
    return (
        observation.actual_energy_wh
        / observation.forecast_central_energy_wh
    )
