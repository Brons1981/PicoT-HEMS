from datetime import UTC, datetime, timedelta

import pytest
from picot.v2.pv_attenuation_history import (
    build_pv_attenuation_profile_from_history,
)

from picot.v2.contracts import PVAttenuationObservation
from picot.v2.pv_attenuation_aggregation import (
    PVAttenuationAggregationConfig,
)
from picot.v2.pv_attenuation_eligibility import (
    PVAttenuationEligibilityConfig,
)
from picot.v2.pv_attenuation_evidence import PVAttenuationEvidenceStore

EVALUATED_AT = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
BASE_START = datetime(2026, 8, 13, 17, 0, tzinfo=UTC)


def _observation(
    *,
    day_offset: int,
    position: str,
    ratio: float,
    installation_scope_id: str = "pv-installation-home",
) -> PVAttenuationObservation:
    position_minutes = {
        "preceding": -30,
        "target": 0,
        "following": 30,
    }
    sunset_minutes = {
        "preceding": -105.0,
        "target": -75.0,
        "following": -45.0,
    }
    starts_at = (
        BASE_START
        + timedelta(days=day_offset)
        + timedelta(minutes=position_minutes[position])
    )
    central = 200.0
    observation_id = (
        f"{installation_scope_id}-{day_offset}-{position}"
    )
    return PVAttenuationObservation(
        observation_id=observation_id,
        installation_scope_id=installation_scope_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        forecast_captured_at=starts_at - timedelta(hours=6),
        forecast_lower_energy_wh=120.0,
        forecast_central_energy_wh=central,
        forecast_upper_energy_wh=280.0,
        forecast_confidence=0.8,
        actual_energy_wh=central * ratio,
        actual_confidence=1.0,
        solar_azimuth_degrees=265.0,
        solar_elevation_degrees=9.0,
        minutes_from_sunset=sunset_minutes[position],
        forecast_evidence_ids=(f"forecast-{observation_id}",),
        actual_evidence_ids=(f"actual-{observation_id}",),
        forecast_mapping_version="solcast-combined-installation:v1",
        forecast_conversion_method_version=(
            "solcast-average-kw-30m:v1"
        ),
        actual_conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
        ),
        eligibility_status="unassessed",
        eligibility_reason="eligibility_not_assessed",
        eligibility_method_version="not_applied",
        alignment_status="aligned",
        coverage_status="complete",
        observation_method_version=(
            "pv-attenuation-evidence-capture:v1"
        ),
    )


def _day(
    day_offset: int,
    *,
    target_ratio: float,
    installation_scope_id: str = "pv-installation-home",
) -> tuple[PVAttenuationObservation, ...]:
    return (
        _observation(
            day_offset=day_offset,
            position="preceding",
            ratio=0.95,
            installation_scope_id=installation_scope_id,
        ),
        _observation(
            day_offset=day_offset,
            position="target",
            ratio=target_ratio,
            installation_scope_id=installation_scope_id,
        ),
        _observation(
            day_offset=day_offset,
            position="following",
            ratio=min(target_ratio + 0.05, 0.7),
            installation_scope_id=installation_scope_id,
        ),
    )


def _eligibility_config() -> PVAttenuationEligibilityConfig:
    return PVAttenuationEligibilityConfig(
        minimum_forecast_energy_wh=100.0,
        minimum_forecast_confidence=0.3,
        minimum_actual_confidence=0.9,
        maximum_attenuation_ratio=0.7,
        minimum_preceding_tracking_ratio=0.8,
        maximum_preceding_tracking_ratio=1.2,
        minimum_distinct_days=3,
        sunset_bucket_tolerance_minutes=20.0,
        maximum_evidence_age_days=45,
        configuration_version=(
            "pv-attenuation-eligibility-config:v1"
        ),
    )


def _aggregation_config() -> PVAttenuationAggregationConfig:
    return PVAttenuationAggregationConfig(
        sunset_bucket_width_minutes=30.0,
        minimum_sample_count=3,
        minimum_distinct_days=3,
        maximum_dispersion=0.2,
        minimum_profile_confidence=0.4,
        maximum_evidence_age_days=45,
        profile_validity_days=7,
        configuration_version=(
            "pv-attenuation-aggregation-config:v1"
        ),
    )


def _build(
    store: PVAttenuationEvidenceStore,
):
    return build_pv_attenuation_profile_from_history(
        store=store,
        installation_scope_id="pv-installation-home",
        evaluated_at=EVALUATED_AT,
        eligibility_config=_eligibility_config(),
        aggregation_config=_aggregation_config(),
    )


def test_persisted_multi_day_history_builds_observer_only_profile(
    tmp_path,
) -> None:
    path = tmp_path / "pv-attenuation-history.jsonl"
    store = PVAttenuationEvidenceStore(path)
    observations = (
        *_day(-2, target_ratio=0.4),
        *_day(-1, target_ratio=0.5),
        *_day(0, target_ratio=0.6),
        *_day(
            0,
            target_ratio=0.1,
            installation_scope_id="other-installation",
        ),
    )
    for observation in observations:
        assert store.append(observation) is True
    persisted_before = path.read_text(encoding="utf-8")

    profile = _build(PVAttenuationEvidenceStore(path))

    target_bucket = next(
        bucket
        for bucket in profile.buckets
        if bucket.sunset_offset_starts_minutes == -90.0
    )
    assert profile.status == "available"
    assert profile.observer_only is True
    assert target_bucket.status == "available"
    assert target_bucket.attenuation_factor == pytest.approx(0.5)
    assert target_bucket.sample_count == 3
    assert target_bucket.distinct_day_count == 3
    assert target_bucket.observation_ids == (
        "pv-installation-home--2-target",
        "pv-installation-home--1-target",
        "pv-installation-home-0-target",
    )
    assert all(
        "other-installation" not in observation_id
        for observation_id in (
            *target_bucket.observation_ids,
            *target_bucket.rejected_observation_ids,
        )
    )
    assert target_bucket.configuration_version == (
        "pv-attenuation-aggregation-config:v1"
    )
    assert target_bucket.aggregation_method_version == (
        "pv-attenuation-bucket-median-mad:v1"
    )
    assert path.read_text(encoding="utf-8") == persisted_before


def test_insufficient_history_preserves_factor_one_with_reason(
    tmp_path,
) -> None:
    path = tmp_path / "pv-attenuation-history.jsonl"
    store = PVAttenuationEvidenceStore(path)
    for observation in (
        *_day(-1, target_ratio=0.4),
        *_day(0, target_ratio=0.5),
    ):
        assert store.append(observation) is True

    profile = _build(PVAttenuationEvidenceStore(path))

    target_bucket = next(
        bucket
        for bucket in profile.buckets
        if bucket.sunset_offset_starts_minutes == -90.0
    )
    assert profile.status == "unavailable"
    assert profile.unavailable_reason == "no_available_buckets"
    assert target_bucket.status == "unavailable"
    assert target_bucket.attenuation_factor == 1.0
    assert target_bucket.unavailable_reason == (
        "insufficient_structural_evidence"
    )
    assert target_bucket.sample_count == 0
    assert target_bucket.distinct_day_count == 0
