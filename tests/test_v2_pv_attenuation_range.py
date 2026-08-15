from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.contracts import (
    PVAttenuationBucket,
    PVEnergyTimelineInterval,
    PVForecastAttenuationProfile,
)
from picot.v2.pv_attenuation_range import (
    ATTENUATED_RANGE_METHOD_VERSION,
    derive_pv_attenuated_forecast_range,
    project_pv_attenuated_forecast_range,
)

START = datetime(2026, 8, 16, 17, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
PROJECTED_AT = datetime(2026, 8, 15, 22, 0, tzinfo=UTC)


def _forecast(
    *,
    range_status: str = "available",
) -> PVEnergyTimelineInterval:
    return PVEnergyTimelineInterval(
        interval_id="forecast-interval-1",
        starts_at=START,
        ends_at=END,
        pv_energy_wh=200.0,
        evidence_type="FORECAST",
        confidence=0.42,
        actual_evidence_ids=(),
        forecast_evidence_ids=("solcast-forecast-1",),
        conversion_method_version="solcast-average-kw-30m:v1",
        forecast_lower_energy_wh=(
            100.0 if range_status == "available" else None
        ),
        forecast_central_energy_wh=(
            200.0 if range_status == "available" else None
        ),
        forecast_upper_energy_wh=(
            300.0 if range_status == "available" else None
        ),
        forecast_range_status=range_status,
        forecast_range_source_fields=(
            ("estimate10", "estimate", "estimate90")
            if range_status == "available"
            else ()
        ),
        forecast_range_method_version=(
            "solcast-range:v1"
            if range_status == "available"
            else None
        ),
    )


def _bucket(
    *,
    status: str = "available",
    factor: float = 0.5,
    unavailable_reason: str | None = None,
) -> PVAttenuationBucket:
    return PVAttenuationBucket(
        bucket_id="attenuation-bucket-1",
        installation_scope_id="pv-installation-home",
        sunset_offset_starts_minutes=-90.0,
        sunset_offset_ends_minutes=-60.0,
        attenuation_factor=factor,
        status=status,
        unavailable_reason=unavailable_reason,
        sample_count=9,
        distinct_day_count=5,
        dispersion=0.08,
        profile_confidence=0.75 if status == "available" else 0.0,
        evidence_starts_at=START - timedelta(days=20),
        evidence_ends_at=START - timedelta(days=1),
        updated_at=PROJECTED_AT - timedelta(hours=1),
        observation_ids=("observation-1", "observation-2"),
        rejected_observation_ids=("observation-rejected-1",),
        aggregation_method_version=(
            "pv-attenuation-bucket-median-mad:v1"
        ),
        configuration_version="pv-attenuation-aggregation-config:v1",
    )


def _profile(
    *,
    status: str = "available",
    buckets: tuple[PVAttenuationBucket, ...] | None = None,
    unavailable_reason: str | None = None,
    valid_until: datetime | None = None,
) -> PVForecastAttenuationProfile:
    return PVForecastAttenuationProfile(
        profile_id="attenuation-profile-1",
        installation_scope_id="pv-installation-home",
        status=status,
        unavailable_reason=unavailable_reason,
        valid_from=PROJECTED_AT - timedelta(days=1),
        valid_until=valid_until or PROJECTED_AT + timedelta(days=7),
        updated_at=PROJECTED_AT - timedelta(hours=1),
        observer_only=True,
        buckets=(_bucket(),) if buckets is None else buckets,
        method_version=(
            "pv-attenuation-profile:v1:"
            "pv-attenuation-aggregation-config:v1"
        ),
    )


def _derive(
    *,
    forecast: PVEnergyTimelineInterval | None = None,
    profile: PVForecastAttenuationProfile | None = None,
    minutes_from_sunset: float = -75.0,
    projected_at: datetime = PROJECTED_AT,
):
    return derive_pv_attenuated_forecast_range(
        installation_scope_id="pv-installation-home",
        forecast=forecast or _forecast(),
        profile=_profile() if profile is None else profile,
        minutes_from_sunset=minutes_from_sunset,
        projected_at=projected_at,
    )


def test_available_bucket_projects_original_and_corrected_side_by_side() -> None:
    forecast = _forecast()
    result = _derive(forecast=forecast)

    assert result.status == "available"
    assert result.unavailable_reason is None
    assert result.observer_only is True
    assert result.source_interval_id == forecast.interval_id
    assert result.original_lower_energy_wh == 100.0
    assert result.original_central_energy_wh == 200.0
    assert result.original_upper_energy_wh == 300.0
    assert result.source_confidence == 0.42
    assert result.profile_id == "attenuation-profile-1"
    assert result.bucket_id == "attenuation-bucket-1"
    assert result.attenuation_factor == 0.5
    assert result.corrected_lower_energy_wh == 50.0
    assert result.corrected_central_energy_wh == 100.0
    assert result.corrected_upper_energy_wh == 150.0
    assert result.profile_confidence == 0.75
    assert result.forecast_evidence_ids == ("solcast-forecast-1",)
    assert result.observation_ids == (
        "observation-1",
        "observation-2",
    )
    assert result.rejected_observation_ids == (
        "observation-rejected-1",
    )
    assert result.correction_method_version == (
        ATTENUATED_RANGE_METHOD_VERSION
    )


def test_original_forecast_object_is_never_modified() -> None:
    forecast = _forecast()

    result = _derive(forecast=forecast)

    assert forecast.pv_energy_wh == 200.0
    assert forecast.forecast_lower_energy_wh == 100.0
    assert forecast.forecast_central_energy_wh == 200.0
    assert forecast.forecast_upper_energy_wh == 300.0
    assert result.corrected_central_energy_wh == 100.0


def test_result_is_immutable_and_identity_is_deterministic() -> None:
    first = _derive()
    second = _derive()

    assert first.derivation_id == second.derivation_id
    assert first.derivation_id.startswith("pv-attenuated-range-")
    with pytest.raises(FrozenInstanceError):
        first.attenuation_factor = 0.7  # type: ignore[misc]


@pytest.mark.parametrize(
    ("profile", "offset", "projected_at", "reason"),
    (
        (
            _profile(
                status="unavailable",
                buckets=(),
                unavailable_reason="no_available_buckets",
            ),
            -75.0,
            PROJECTED_AT,
            "profile_unavailable",
        ),
        (
            _profile(
                buckets=(
                    _bucket(
                        status="unavailable",
                        factor=1.0,
                        unavailable_reason="conflicting_evidence",
                    ),
                ),
            ),
            -75.0,
            PROJECTED_AT,
            "bucket_unavailable",
        ),
        (
            _profile(),
            -30.0,
            PROJECTED_AT,
            "no_matching_bucket",
        ),
        (
            _profile(valid_until=PROJECTED_AT),
            -75.0,
            PROJECTED_AT,
            "profile_outside_validity",
        ),
    ),
)
def test_profile_fallbacks_are_visible_and_apply_factor_one(
    profile: PVForecastAttenuationProfile,
    offset: float,
    projected_at: datetime,
    reason: str,
) -> None:
    result = _derive(
        profile=profile,
        minutes_from_sunset=offset,
        projected_at=projected_at,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == reason
    assert result.attenuation_factor == 1.0
    assert result.corrected_lower_energy_wh == (
        result.original_lower_energy_wh
    )
    assert result.corrected_central_energy_wh == (
        result.original_central_energy_wh
    )
    assert result.corrected_upper_energy_wh == (
        result.original_upper_energy_wh
    )


def test_absent_profile_is_explicit_and_preserves_source_range() -> None:
    result = derive_pv_attenuated_forecast_range(
        installation_scope_id="pv-installation-home",
        forecast=_forecast(),
        profile=None,
        minutes_from_sunset=-75.0,
        projected_at=PROJECTED_AT,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "profile_missing"
    assert result.profile_id is None
    assert result.bucket_id is None
    assert result.attenuation_factor == 1.0
    assert result.profile_confidence is None


def test_missing_source_range_is_not_invented() -> None:
    result = _derive(forecast=_forecast(range_status="unavailable"))

    assert result.status == "unavailable"
    assert result.unavailable_reason == "source_range_unavailable"
    assert result.original_lower_energy_wh is None
    assert result.original_central_energy_wh is None
    assert result.original_upper_energy_wh is None
    assert result.corrected_lower_energy_wh is None
    assert result.corrected_central_energy_wh is None
    assert result.corrected_upper_energy_wh is None
    assert result.attenuation_factor == 1.0


def test_profile_for_other_installation_scope_is_never_applied() -> None:
    foreign_bucket = replace(
        _bucket(),
        installation_scope_id="other-installation",
    )
    foreign_profile = replace(
        _profile(),
        installation_scope_id="other-installation",
        buckets=(foreign_bucket,),
    )

    result = _derive(profile=foreign_profile)

    assert result.status == "unavailable"
    assert result.unavailable_reason == "installation_scope_mismatch"
    assert result.attenuation_factor == 1.0


def test_projection_exposes_both_ranges_and_separate_confidences() -> None:
    fields = project_pv_attenuated_forecast_range(_derive())

    assert fields["pv_attenuation_original_lower_energy_wh"] == 100.0
    assert fields["pv_attenuation_original_central_energy_wh"] == 200.0
    assert fields["pv_attenuation_original_upper_energy_wh"] == 300.0
    assert fields["pv_attenuation_corrected_lower_energy_wh"] == 50.0
    assert fields["pv_attenuation_corrected_central_energy_wh"] == 100.0
    assert fields["pv_attenuation_corrected_upper_energy_wh"] == 150.0
    assert fields["pv_attenuation_source_confidence"] == 0.42
    assert fields["pv_attenuation_profile_confidence"] == 0.75
    assert "pv_attenuation_combined_confidence" not in fields
    assert fields["pv_attenuation_factor"] == 0.5
    assert fields["pv_attenuation_profile_id"] == "attenuation-profile-1"
    assert fields["pv_attenuation_bucket_id"] == "attenuation-bucket-1"
    assert fields["pv_attenuation_observer_only"] is True
