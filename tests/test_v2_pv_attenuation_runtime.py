from datetime import UTC, datetime, timedelta

from picot.v2.contracts import (
    PVAttenuationBucket,
    PVEnergyTimelineInterval,
    PVForecastAttenuationProfile,
)
from picot.v2.pipeline import CanonicalPipeline
from picot.v2.projection import project
from picot.v2.pv_attenuation_range import (
    derive_pv_attenuated_forecast_range,
)
from picot.v2.pv_attenuation_runtime import (
    ATTENUATION_RUNTIME_PROJECTION_METHOD_VERSION,
    attach_pv_attenuation_runtime_diagnostics,
    project_live_pv_attenuation_ranges,
)

START = datetime(2026, 8, 16, 17, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
PROJECTED_AT = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


def _forecast() -> PVEnergyTimelineInterval:
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
        forecast_lower_energy_wh=100.0,
        forecast_central_energy_wh=200.0,
        forecast_upper_energy_wh=300.0,
        forecast_range_status="available",
        forecast_range_source_fields=(
            "estimate10",
            "estimate",
            "estimate90",
        ),
        forecast_range_method_version="solcast-range:v1",
    )


def _profile() -> PVForecastAttenuationProfile:
    bucket = PVAttenuationBucket(
        bucket_id="attenuation-bucket-1",
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
    return PVForecastAttenuationProfile(
        profile_id="attenuation-profile-1",
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


def _range():
    return derive_pv_attenuated_forecast_range(
        installation_scope_id="pv-installation-home",
        forecast=_forecast(),
        profile=_profile(),
        minutes_from_sunset=-75.0,
        projected_at=PROJECTED_AT,
    )


def test_runtime_projection_exposes_summary_and_interval_lineage() -> None:
    result = _range()

    fields = project_live_pv_attenuation_ranges((result,))

    assert fields["pv_attenuation_runtime_status"] == "available"
    assert fields["pv_attenuation_runtime_unavailable_reason"] is None
    assert fields["pv_attenuation_runtime_observer_only"] is True
    assert fields["pv_attenuation_runtime_interval_count"] == 1
    assert fields["pv_attenuation_runtime_available_interval_count"] == 1
    assert fields["pv_attenuation_runtime_unavailable_interval_count"] == 0
    assert fields["pv_attenuation_runtime_original_central_total_wh"] == 200.0
    assert fields["pv_attenuation_runtime_corrected_central_total_wh"] == 100.0
    assert fields["pv_attenuation_runtime_correction_delta_wh"] == -100.0
    assert fields["pv_attenuation_runtime_profile_ids"] == [
        "attenuation-profile-1"
    ]
    assert fields["pv_attenuation_runtime_bucket_ids"] == [
        "attenuation-bucket-1"
    ]
    assert fields["pv_attenuation_runtime_projection_method_version"] == (
        ATTENUATION_RUNTIME_PROJECTION_METHOD_VERSION
    )

    intervals = fields["pv_attenuation_runtime_intervals"]
    assert isinstance(intervals, list)
    assert intervals == [
        {
            "pv_attenuation_derivation_id": result.derivation_id,
            "pv_attenuation_installation_scope_id": (
                "pv-installation-home"
            ),
            "pv_attenuation_source_interval_id": "forecast-interval-1",
            "pv_attenuation_starts_at": START.isoformat(),
            "pv_attenuation_ends_at": END.isoformat(),
            "pv_attenuation_projected_at": PROJECTED_AT.isoformat(),
            "pv_attenuation_status": "available",
            "pv_attenuation_unavailable_reason": None,
            "pv_attenuation_observer_only": True,
            "pv_attenuation_original_lower_energy_wh": 100.0,
            "pv_attenuation_original_central_energy_wh": 200.0,
            "pv_attenuation_original_upper_energy_wh": 300.0,
            "pv_attenuation_corrected_lower_energy_wh": 50.0,
            "pv_attenuation_corrected_central_energy_wh": 100.0,
            "pv_attenuation_corrected_upper_energy_wh": 150.0,
            "pv_attenuation_source_confidence": 0.42,
            "pv_attenuation_profile_id": "attenuation-profile-1",
            "pv_attenuation_bucket_id": "attenuation-bucket-1",
            "pv_attenuation_factor": 0.5,
            "pv_attenuation_profile_confidence": 0.75,
            "pv_attenuation_forecast_evidence_ids": (
                "solcast-forecast-1",
            ),
            "pv_attenuation_observation_ids": (
                "observation-1",
                "observation-2",
            ),
            "pv_attenuation_rejected_observation_ids": (
                "observation-rejected-1",
            ),
            "pv_attenuation_source_range_method_version": (
                "solcast-range:v1"
            ),
            "pv_attenuation_correction_method_version": (
                "pv-attenuated-forecast-range:v1"
            ),
        }
    ]


def test_empty_runtime_projection_is_explicit_not_available() -> None:
    fields = project_live_pv_attenuation_ranges(())

    assert fields["pv_attenuation_runtime_status"] == "not_available"
    assert fields["pv_attenuation_runtime_unavailable_reason"] == (
        "no_derived_ranges"
    )
    assert fields["pv_attenuation_runtime_observer_only"] is True
    assert fields["pv_attenuation_runtime_interval_count"] == 0
    assert fields["pv_attenuation_runtime_original_central_total_wh"] is None
    assert fields["pv_attenuation_runtime_corrected_central_total_wh"] is None
    assert fields["pv_attenuation_runtime_correction_delta_wh"] is None
    assert fields["pv_attenuation_runtime_intervals"] == []


def test_runtime_attachment_only_enriches_planning_input_card() -> None:
    run = CanonicalPipeline().run(captured_at=PROJECTED_AT)
    original = project(run)

    enriched = attach_pv_attenuation_runtime_diagnostics(
        original,
        (_range(),),
    )

    assert len(enriched.cards) == 9
    assert enriched.cards[1:] == original.cards[1:]
    assert enriched.cards[0].entity_id == original.cards[0].entity_id
    assert enriched.cards[0].state == original.cards[0].state
    assert enriched.cards[0].attributes[
        "pv_attenuation_runtime_status"
    ] == "available"
    assert enriched.cards[0].attributes[
        "pv_attenuation_runtime_observer_only"
    ] is True
    assert "pv_attenuation_selected_energy_wh" not in (
        enriched.cards[0].attributes
    )
    assert "pv_attenuation_combined_confidence" not in (
        enriched.cards[0].attributes
    )
