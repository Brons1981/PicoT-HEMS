from datetime import UTC, datetime, timedelta

from picot.v2.contracts import (
    PVAttenuationBucket,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
    PVForecastAttenuationProfile,
)
from picot.v2.pv_attenuation_runtime_derivation import (
    RUNTIME_DERIVATION_METHOD_VERSION,
    derive_live_pv_attenuation_ranges,
)

PROJECTED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _forecast(
    interval_id: str,
    starts_at: datetime,
    *,
    range_status: str = "available",
) -> PVEnergyTimelineInterval:
    central = 200.0
    return PVEnergyTimelineInterval(
        interval_id=interval_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=central,
        evidence_type="FORECAST",
        confidence=0.42,
        actual_evidence_ids=(),
        forecast_evidence_ids=(f"evidence-{interval_id}",),
        conversion_method_version="solcast-average-kw-30m:v1",
        forecast_lower_energy_wh=(
            100.0 if range_status == "available" else None
        ),
        forecast_central_energy_wh=(
            central if range_status == "available" else None
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


def _timeline() -> PVEnergyTimeline:
    return PVEnergyTimeline(
        timeline_id="pv-timeline-runtime",
        run_id="run-runtime",
        snapshot_id="snapshot-runtime",
        intervals=(
            _forecast(
                "closed-interval",
                PROJECTED_AT - timedelta(minutes=30),
            ),
            _forecast("future-matched", PROJECTED_AT),
            _forecast(
                "future-offset-missing",
                PROJECTED_AT + timedelta(minutes=30),
            ),
        ),
    )


def _profile() -> PVForecastAttenuationProfile:
    bucket = PVAttenuationBucket(
        bucket_id="bucket-evening",
        installation_scope_id="pv-installation-home",
        sunset_offset_starts_minutes=-90.0,
        sunset_offset_ends_minutes=-60.0,
        attenuation_factor=0.5,
        status="available",
        unavailable_reason=None,
        sample_count=9,
        distinct_day_count=5,
        dispersion=0.08,
        profile_confidence=0.75,
        evidence_starts_at=PROJECTED_AT - timedelta(days=20),
        evidence_ends_at=PROJECTED_AT - timedelta(days=1),
        updated_at=PROJECTED_AT - timedelta(hours=1),
        observation_ids=("observation-1", "observation-2"),
        rejected_observation_ids=(),
        aggregation_method_version=(
            "pv-attenuation-bucket-median-mad:v1"
        ),
        configuration_version="pv-attenuation-aggregation-config:v1",
    )
    return PVForecastAttenuationProfile(
        profile_id="profile-home",
        installation_scope_id="pv-installation-home",
        status="available",
        unavailable_reason=None,
        valid_from=PROJECTED_AT - timedelta(days=1),
        valid_until=PROJECTED_AT + timedelta(days=7),
        updated_at=PROJECTED_AT - timedelta(hours=1),
        observer_only=True,
        buckets=(bucket,),
        method_version=(
            "pv-attenuation-profile:v1:"
            "pv-attenuation-aggregation-config:v1"
        ),
    )


def test_runtime_derives_every_future_forecast_without_silent_skips() -> None:
    timeline = _timeline()

    results = derive_live_pv_attenuation_ranges(
        installation_scope_id="pv-installation-home",
        timeline=timeline,
        profile=_profile(),
        minutes_from_sunset_by_interval_id={
            "future-matched": -75.0,
        },
        projected_at=PROJECTED_AT,
    )

    assert tuple(result.source_interval_id for result in results) == (
        "future-matched",
        "future-offset-missing",
    )
    matched, missing = results
    assert matched.status == "available"
    assert matched.attenuation_factor == 0.5
    assert matched.original_central_energy_wh == 200.0
    assert matched.corrected_central_energy_wh == 100.0
    assert missing.status == "unavailable"
    assert missing.unavailable_reason == "sunset_offset_missing"
    assert missing.attenuation_factor == 1.0
    assert missing.original_central_energy_wh == 200.0
    assert missing.corrected_central_energy_wh == 200.0


def test_missing_profile_preserves_all_future_source_ranges() -> None:
    results = derive_live_pv_attenuation_ranges(
        installation_scope_id="pv-installation-home",
        timeline=_timeline(),
        profile=None,
        minutes_from_sunset_by_interval_id={},
        projected_at=PROJECTED_AT,
    )

    assert len(results) == 2
    assert all(result.status == "unavailable" for result in results)
    assert all(
        result.unavailable_reason == "profile_missing"
        for result in results
    )
    assert all(result.attenuation_factor == 1.0 for result in results)
    assert all(
        result.corrected_central_energy_wh
        == result.original_central_energy_wh
        for result in results
    )


def test_runtime_derivation_is_deterministic_and_does_not_mutate_timeline() -> None:
    timeline = _timeline()
    original_intervals = timeline.intervals
    kwargs = {
        "installation_scope_id": "pv-installation-home",
        "timeline": timeline,
        "profile": _profile(),
        "minutes_from_sunset_by_interval_id": {
            "future-matched": -75.0,
            "future-offset-missing": -45.0,
        },
        "projected_at": PROJECTED_AT,
    }

    first = derive_live_pv_attenuation_ranges(**kwargs)
    second = derive_live_pv_attenuation_ranges(**kwargs)

    assert first == second
    assert timeline.intervals is original_intervals
    assert timeline.intervals[1].pv_energy_wh == 200.0
    assert timeline.intervals[1].forecast_central_energy_wh == 200.0


def test_source_range_unavailable_remains_explicit() -> None:
    timeline = PVEnergyTimeline(
        timeline_id="pv-timeline-unavailable-range",
        run_id="run-runtime",
        snapshot_id="snapshot-runtime",
        intervals=(
            _forecast(
                "future-range-unavailable",
                PROJECTED_AT,
                range_status="unavailable",
            ),
        ),
    )

    result = derive_live_pv_attenuation_ranges(
        installation_scope_id="pv-installation-home",
        timeline=timeline,
        profile=_profile(),
        minutes_from_sunset_by_interval_id={
            "future-range-unavailable": -75.0,
        },
        projected_at=PROJECTED_AT,
    )[0]

    assert result.status == "unavailable"
    assert result.unavailable_reason == "source_range_unavailable"
    assert result.original_central_energy_wh is None
    assert result.corrected_central_energy_wh is None


def test_runtime_derivation_method_version_is_explicit() -> None:
    assert RUNTIME_DERIVATION_METHOD_VERSION == (
        "pv-attenuation-runtime-derivation:v1"
    )
