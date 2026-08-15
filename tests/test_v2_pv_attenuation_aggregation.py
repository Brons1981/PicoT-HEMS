from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest
from picot.v2.pv_attenuation_aggregation import (
    AGGREGATION_METHOD_VERSION,
    PROFILE_METHOD_VERSION,
    PVAttenuationAggregationConfig,
    aggregate_pv_attenuation_profile,
)

from picot.v2.contracts import PVAttenuationObservation

EVALUATED_AT = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
BASE_START = datetime(2026, 8, 13, 17, 0, tzinfo=UTC)


def _observation(
    *,
    observation_id: str,
    day_offset: int,
    minutes_from_sunset: float,
    ratio: float,
    status: str = "eligible",
    reason: str | None = None,
    installation_scope_id: str = "pv-installation-home",
    forecast_confidence: float = 0.8,
    actual_confidence: float = 1.0,
) -> PVAttenuationObservation:
    starts_at = BASE_START + timedelta(days=day_offset)
    central = 200.0
    return PVAttenuationObservation(
        observation_id=observation_id,
        installation_scope_id=installation_scope_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        forecast_captured_at=starts_at - timedelta(hours=6),
        forecast_lower_energy_wh=120.0,
        forecast_central_energy_wh=central,
        forecast_upper_energy_wh=280.0,
        forecast_confidence=forecast_confidence,
        actual_energy_wh=central * ratio,
        actual_confidence=actual_confidence,
        solar_azimuth_degrees=265.0,
        solar_elevation_degrees=9.0,
        minutes_from_sunset=minutes_from_sunset,
        forecast_evidence_ids=(f"forecast-{observation_id}",),
        actual_evidence_ids=(f"actual-{observation_id}",),
        forecast_mapping_version="solcast-combined-installation:v1",
        forecast_conversion_method_version="solcast-average-kw-30m:v1",
        actual_conversion_method_version="goodwe-step-hold-energy:v1",
        eligibility_status=status,
        eligibility_reason=reason,
        eligibility_method_version=(
            "pv-attenuation-eligibility:v1:config:v1"
        ),
        alignment_status="aligned",
        coverage_status="complete",
        observation_method_version="pv-attenuation-evidence-capture:v1",
    )


def _eligible_evidence() -> tuple[PVAttenuationObservation, ...]:
    return (
        _observation(
            observation_id="eligible-day-1",
            day_offset=0,
            minutes_from_sunset=-74.0,
            ratio=0.4,
        ),
        _observation(
            observation_id="eligible-day-2",
            day_offset=1,
            minutes_from_sunset=-75.0,
            ratio=0.5,
        ),
        _observation(
            observation_id="eligible-day-3",
            day_offset=2,
            minutes_from_sunset=-76.0,
            ratio=0.6,
        ),
    )


def _config(**overrides: object) -> PVAttenuationAggregationConfig:
    values: dict[str, object] = {
        "sunset_bucket_width_minutes": 30.0,
        "minimum_sample_count": 3,
        "minimum_distinct_days": 3,
        "maximum_dispersion": 0.2,
        "minimum_profile_confidence": 0.4,
        "maximum_evidence_age_days": 45,
        "profile_validity_days": 7,
        "configuration_version": "pv-attenuation-aggregation-config:v1",
    }
    values.update(overrides)
    return PVAttenuationAggregationConfig(**values)


def _aggregate(
    observations: tuple[PVAttenuationObservation, ...],
    *,
    config: PVAttenuationAggregationConfig | None = None,
):
    return aggregate_pv_attenuation_profile(
        installation_scope_id="pv-installation-home",
        observations=observations,
        evaluated_at=EVALUATED_AT,
        config=config or _config(),
    )


def test_aggregation_config_is_immutable_and_versioned() -> None:
    config = _config()

    assert config.configuration_version == (
        "pv-attenuation-aggregation-config:v1"
    )
    with pytest.raises(FrozenInstanceError):
        config.minimum_sample_count = 1  # type: ignore[misc]


def test_available_bucket_uses_median_ratio_and_visible_dispersion() -> None:
    profile = _aggregate(_eligible_evidence())
    bucket = profile.buckets[0]

    assert profile.status == "available"
    assert profile.unavailable_reason is None
    assert profile.observer_only is True
    assert bucket.status == "available"
    assert bucket.unavailable_reason is None
    assert bucket.sunset_offset_starts_minutes == -90.0
    assert bucket.sunset_offset_ends_minutes == -60.0
    assert bucket.attenuation_factor == pytest.approx(0.5)
    assert bucket.sample_count == 3
    assert bucket.distinct_day_count == 3
    assert bucket.dispersion == pytest.approx(0.1)
    assert bucket.profile_confidence == pytest.approx(0.5)
    assert bucket.observation_ids == (
        "eligible-day-1",
        "eligible-day-2",
        "eligible-day-3",
    )
    assert bucket.rejected_observation_ids == ()
    assert bucket.aggregation_method_version == (
        AGGREGATION_METHOD_VERSION
    )
    assert bucket.configuration_version == (
        "pv-attenuation-aggregation-config:v1"
    )
    assert profile.method_version == (
        f"{PROFILE_METHOD_VERSION}:"
        "pv-attenuation-aggregation-config:v1"
    )


def test_rejected_observations_are_retained_but_never_enter_factor() -> None:
    rejected = _observation(
        observation_id="rejected-cloud",
        day_offset=2,
        minutes_from_sunset=-75.0,
        ratio=0.05,
        status="rejected",
        reason="forecast_not_tracked_before_window",
    )
    profile = _aggregate((*_eligible_evidence(), rejected))
    bucket = profile.buckets[0]

    assert bucket.attenuation_factor == pytest.approx(0.5)
    assert bucket.sample_count == 3
    assert bucket.observation_ids == (
        "eligible-day-1",
        "eligible-day-2",
        "eligible-day-3",
    )
    assert bucket.rejected_observation_ids == ("rejected-cloud",)


def test_buckets_are_deterministic_and_chronologically_ordered() -> None:
    later = tuple(
        _observation(
            observation_id=f"later-{index}",
            day_offset=index,
            minutes_from_sunset=-44.0 - index,
            ratio=0.7,
        )
        for index in range(3)
    )
    observations = tuple(reversed((*later, *_eligible_evidence())))

    first = _aggregate(observations)
    second = _aggregate(observations)

    assert first.profile_id == second.profile_id
    assert tuple(bucket.bucket_id for bucket in first.buckets) == tuple(
        bucket.bucket_id for bucket in second.buckets
    )
    assert tuple(
        bucket.sunset_offset_starts_minutes
        for bucket in first.buckets
    ) == (-90.0, -60.0)


def test_insufficient_recurrence_fails_to_explicit_factor_one() -> None:
    profile = _aggregate(_eligible_evidence()[:2])
    bucket = profile.buckets[0]

    assert profile.status == "unavailable"
    assert profile.unavailable_reason == "no_available_buckets"
    assert bucket.status == "unavailable"
    assert bucket.unavailable_reason == (
        "insufficient_structural_evidence"
    )
    assert bucket.attenuation_factor == 1.0
    assert bucket.sample_count == 2
    assert bucket.distinct_day_count == 2
    assert bucket.profile_confidence == 0.0


def test_conflicting_evidence_is_visible_and_not_smoothed() -> None:
    observations = (
        _observation(
            observation_id="low",
            day_offset=0,
            minutes_from_sunset=-75.0,
            ratio=0.1,
        ),
        _observation(
            observation_id="middle",
            day_offset=1,
            minutes_from_sunset=-75.0,
            ratio=0.5,
        ),
        _observation(
            observation_id="high",
            day_offset=2,
            minutes_from_sunset=-75.0,
            ratio=0.9,
        ),
    )
    profile = _aggregate(observations)
    bucket = profile.buckets[0]

    assert bucket.status == "unavailable"
    assert bucket.unavailable_reason == "conflicting_evidence"
    assert bucket.attenuation_factor == 1.0
    assert bucket.dispersion == pytest.approx(0.4)
    assert bucket.profile_confidence == 0.0


def test_low_computed_profile_confidence_is_explicitly_unavailable() -> None:
    evidence = tuple(
        _observation(
            observation_id=item.observation_id,
            day_offset=index,
            minutes_from_sunset=item.minutes_from_sunset,
            ratio=item.actual_energy_wh
            / item.forecast_central_energy_wh,
            forecast_confidence=0.35,
        )
        for index, item in enumerate(_eligible_evidence())
    )
    profile = _aggregate(evidence)
    bucket = profile.buckets[0]

    assert bucket.status == "unavailable"
    assert bucket.unavailable_reason == "profile_confidence_below_minimum"
    assert bucket.attenuation_factor == 1.0
    assert bucket.profile_confidence == pytest.approx(0.35)


def test_other_installation_scope_is_excluded_from_all_lineage() -> None:
    other = tuple(
        _observation(
            observation_id=f"other-{index}",
            day_offset=index,
            minutes_from_sunset=-75.0,
            ratio=0.1,
            installation_scope_id="other-installation",
        )
        for index in range(3)
    )
    profile = _aggregate((*_eligible_evidence(), *other))
    bucket = profile.buckets[0]

    assert bucket.attenuation_factor == pytest.approx(0.5)
    assert all(
        not observation_id.startswith("other-")
        for observation_id in (
            *bucket.observation_ids,
            *bucket.rejected_observation_ids,
        )
    )


def test_empty_scope_produces_visible_unavailable_profile() -> None:
    profile = _aggregate(())

    assert profile.status == "unavailable"
    assert profile.unavailable_reason == "no_classified_observations"
    assert profile.buckets == ()
    assert profile.observer_only is True
    assert profile.valid_from == EVALUATED_AT
    assert profile.valid_until == EVALUATED_AT + timedelta(days=7)


def test_stale_bucket_never_reuses_cached_looking_factor() -> None:
    profile = aggregate_pv_attenuation_profile(
        installation_scope_id="pv-installation-home",
        observations=_eligible_evidence(),
        evaluated_at=EVALUATED_AT + timedelta(days=60),
        config=_config(),
    )
    bucket = profile.buckets[0]

    assert bucket.status == "unavailable"
    assert bucket.unavailable_reason == "stale_profile"
    assert bucket.attenuation_factor == 1.0
    assert bucket.profile_confidence == 0.0
