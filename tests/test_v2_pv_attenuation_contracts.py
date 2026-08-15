from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2 import contracts

START = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
CAPTURED = START - timedelta(hours=6)
UPDATED = END + timedelta(hours=1)


def observation_type() -> type:
    assert "PVAttenuationObservation" in contracts.__dict__, (
        "V2ADR-049 observation contract is missing"
    )
    return contracts.__dict__["PVAttenuationObservation"]


def bucket_type() -> type:
    assert "PVAttenuationBucket" in contracts.__dict__, (
        "V2ADR-049 bucket contract is missing"
    )
    return contracts.__dict__["PVAttenuationBucket"]


def profile_type() -> type:
    assert "PVForecastAttenuationProfile" in contracts.__dict__, (
        "V2ADR-049 profile contract is missing"
    )
    return contracts.__dict__["PVForecastAttenuationProfile"]


def make_observation(**overrides: object) -> object:
    values: dict[str, object] = {
        "observation_id": "pv-attenuation-observation-1",
        "installation_scope_id": "pv-installation-home",
        "starts_at": START,
        "ends_at": END,
        "forecast_captured_at": CAPTURED,
        "forecast_lower_energy_wh": 300.0,
        "forecast_central_energy_wh": 500.0,
        "forecast_upper_energy_wh": 700.0,
        "forecast_confidence": 0.72,
        "actual_energy_wh": 180.0,
        "actual_confidence": 1.0,
        "solar_azimuth_degrees": 245.0,
        "solar_elevation_degrees": 14.0,
        "minutes_from_sunset": -150.0,
        "forecast_evidence_ids": ("forecast-evidence-1",),
        "actual_evidence_ids": ("actual-evidence-1",),
        "forecast_mapping_version": "solcast-mapping:v1",
        "forecast_conversion_method_version": (
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
        "actual_conversion_method_version": (
            "goodwe-state-transition-step-hold-energy:v1"
        ),
        "eligibility_status": "eligible",
        "eligibility_reason": None,
        "eligibility_method_version": (
            "pv-attenuation-eligibility:v1"
        ),
    }
    values.update(overrides)
    return observation_type()(**values)


def make_bucket(**overrides: object) -> object:
    values: dict[str, object] = {
        "bucket_id": "pv-attenuation-bucket-1",
        "installation_scope_id": "pv-installation-home",
        "sunset_offset_starts_minutes": -180.0,
        "sunset_offset_ends_minutes": -150.0,
        "attenuation_factor": 0.55,
        "status": "available",
        "unavailable_reason": None,
        "sample_count": 12,
        "distinct_day_count": 6,
        "dispersion": 0.08,
        "profile_confidence": 0.82,
        "evidence_starts_at": START - timedelta(days=14),
        "evidence_ends_at": END - timedelta(days=1),
        "updated_at": UPDATED,
        "observation_ids": (
            "pv-attenuation-observation-1",
            "pv-attenuation-observation-2",
        ),
        "rejected_observation_ids": (
            "pv-attenuation-observation-rejected-1",
        ),
        "aggregation_method_version": (
            "pv-attenuation-bucket-median:v1"
        ),
        "configuration_version": "pv-attenuation-config:v1",
    }
    values.update(overrides)
    return bucket_type()(**values)


def make_profile(
    *,
    buckets: tuple[object, ...] | None = None,
    **overrides: object,
) -> object:
    values: dict[str, object] = {
        "profile_id": "pv-attenuation-profile-1",
        "installation_scope_id": "pv-installation-home",
        "status": "available",
        "unavailable_reason": None,
        "valid_from": START - timedelta(days=14),
        "valid_until": START + timedelta(days=30),
        "updated_at": UPDATED,
        "observer_only": True,
        "buckets": buckets or (make_bucket(),),
        "method_version": "pv-attenuation-profile:v1",
    }
    values.update(overrides)
    return profile_type()(**values)


def test_v2adr049_contracts_are_immutable_and_traceable() -> None:
    observation = make_observation()
    bucket = make_bucket()
    profile = make_profile(buckets=(bucket,))

    assert observation.forecast_central_energy_wh == 500.0
    assert observation.actual_energy_wh == 180.0
    assert observation.minutes_from_sunset == -150.0
    assert observation.forecast_evidence_ids == (
        "forecast-evidence-1",
    )
    assert observation.actual_evidence_ids == ("actual-evidence-1",)
    assert bucket.attenuation_factor == pytest.approx(0.55)
    assert bucket.sample_count == 12
    assert bucket.distinct_day_count == 6
    assert bucket.observation_ids == (
        "pv-attenuation-observation-1",
        "pv-attenuation-observation-2",
    )
    assert profile.installation_scope_id == "pv-installation-home"
    assert profile.observer_only is True
    assert profile.buckets == (bucket,)

    with pytest.raises(FrozenInstanceError):
        observation.actual_energy_wh = 0.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        bucket.attenuation_factor = 1.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.buckets = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        (
            {"ends_at": START},
            "starts_at must be before ends_at",
        ),
        (
            {"starts_at": START.replace(tzinfo=None)},
            "observation datetimes must be timezone-aware",
        ),
        (
            {
                "forecast_lower_energy_wh": 600.0,
                "forecast_central_energy_wh": 500.0,
            },
            "forecast range must satisfy",
        ),
        (
            {"actual_energy_wh": -0.01},
            "actual_energy_wh must not be negative",
        ),
        (
            {"forecast_confidence": 1.01},
            "forecast_confidence must be between 0 and 1",
        ),
        (
            {"actual_confidence": -0.01},
            "actual_confidence must be between 0 and 1",
        ),
        (
            {"solar_azimuth_degrees": 360.01},
            "solar_azimuth_degrees must be between 0 and 360",
        ),
        (
            {"solar_elevation_degrees": 91.0},
            "solar_elevation_degrees must be between -90 and 90",
        ),
        (
            {"forecast_evidence_ids": ()},
            "forecast evidence must be explicit",
        ),
        (
            {"actual_evidence_ids": ()},
            "actual evidence must be explicit",
        ),
    ),
)
def test_attenuation_observation_rejects_invalid_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_observation(**overrides)


def test_rejected_observation_requires_visible_reason() -> None:
    with pytest.raises(
        ValueError,
        match="rejected observation requires eligibility_reason",
    ):
        make_observation(
            eligibility_status="rejected",
            eligibility_reason=None,
        )

    rejected = make_observation(
        eligibility_status="rejected",
        eligibility_reason="forecast_did_not_track_before_window",
    )
    assert (
        rejected.eligibility_reason
        == "forecast_did_not_track_before_window"
    )


@pytest.mark.parametrize("factor", (-0.01, 1.01))
def test_attenuation_bucket_bounds_factor(factor: float) -> None:
    with pytest.raises(
        ValueError,
        match="attenuation_factor must be between 0 and 1",
    ):
        make_bucket(attenuation_factor=factor)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        (
            {
                "sunset_offset_starts_minutes": -150.0,
                "sunset_offset_ends_minutes": -180.0,
            },
            "sunset offset start must be before end",
        ),
        (
            {"sample_count": -1},
            "sample_count must not be negative",
        ),
        (
            {"distinct_day_count": 13},
            "distinct_day_count must not exceed sample_count",
        ),
        (
            {"dispersion": -0.01},
            "dispersion must not be negative",
        ),
        (
            {"profile_confidence": 1.01},
            "profile_confidence must be between 0 and 1",
        ),
        (
            {"updated_at": UPDATED.replace(tzinfo=None)},
            "bucket datetimes must be timezone-aware",
        ),
    ),
)
def test_attenuation_bucket_rejects_invalid_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_bucket(**overrides)


def test_unavailable_bucket_is_explicit_and_applies_no_dampening() -> None:
    bucket = make_bucket(
        status="unavailable",
        unavailable_reason="insufficient_structural_evidence",
        attenuation_factor=1.0,
        sample_count=1,
        distinct_day_count=1,
        profile_confidence=0.0,
    )

    assert bucket.status == "unavailable"
    assert bucket.unavailable_reason == (
        "insufficient_structural_evidence"
    )
    assert bucket.attenuation_factor == 1.0

    with pytest.raises(
        ValueError,
        match="unavailable bucket must use attenuation_factor 1",
    ):
        make_bucket(
            status="unavailable",
            unavailable_reason="insufficient_structural_evidence",
            attenuation_factor=0.8,
        )


def test_profile_rejects_unordered_or_overlapping_buckets() -> None:
    first = make_bucket(
        bucket_id="first",
        sunset_offset_starts_minutes=-180.0,
        sunset_offset_ends_minutes=-150.0,
    )
    overlapping = make_bucket(
        bucket_id="overlapping",
        sunset_offset_starts_minutes=-160.0,
        sunset_offset_ends_minutes=-130.0,
    )
    earlier = make_bucket(
        bucket_id="earlier",
        sunset_offset_starts_minutes=-240.0,
        sunset_offset_ends_minutes=-210.0,
    )

    with pytest.raises(ValueError, match="profile buckets must not overlap"):
        make_profile(buckets=(first, overlapping))

    with pytest.raises(
        ValueError,
        match="profile buckets must be chronologically ordered",
    ):
        make_profile(buckets=(first, earlier))


def test_profile_requires_observer_only_and_explicit_unavailability() -> None:
    with pytest.raises(
        ValueError,
        match="attenuation profile must remain observer-only",
    ):
        make_profile(observer_only=False)

    unavailable = make_profile(
        status="unavailable",
        unavailable_reason="insufficient_structural_evidence",
        buckets=(),
    )
    assert unavailable.buckets == ()
    assert unavailable.unavailable_reason == (
        "insufficient_structural_evidence"
    )

    with pytest.raises(
        ValueError,
        match="unavailable profile requires unavailable_reason",
    ):
        make_profile(
            status="unavailable",
            unavailable_reason=None,
            buckets=(),
        )
