from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from picot.v2.pv_deviation import PVDeviationResult
from picot.v2.pv_attenuation_evidence import (
    ATTENUATION_EVIDENCE_METHOD_VERSION,
    PVAttenuationEvidenceStore,
    build_pv_attenuation_observation,
    project_pv_attenuation_observation,
)


START = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
CAPTURED = START - timedelta(hours=3)
SUNSET = datetime(2026, 8, 15, 18, 58, tzinfo=UTC)


def _deviation(
    *,
    lower: float | None = 120.0,
    central: float | None = 200.0,
    upper: float | None = 300.0,
    range_status: str = "available",
) -> PVDeviationResult:
    return PVDeviationResult(
        deviation_id="pv-deviation-source",
        starts_at=START,
        ends_at=END,
        evaluated_at=END,
        forecast_interval_id="forecast-interval",
        actual_interval_id="actual-interval",
        forecast_energy_wh=200.0,
        forecast_lower_energy_wh=lower,
        forecast_central_energy_wh=central,
        forecast_upper_energy_wh=upper,
        forecast_range_status=range_status,
        forecast_range_source_fields=("estimate10", "estimate", "estimate90"),
        forecast_range_method_version="solcast-range:v1",
        range_assessment="below_range",
        range_distance_wh=70.0,
        range_assessment_method_version="pv-range-assessment:v1",
        actual_energy_wh=50.0,
        deviation_energy_wh=-150.0,
        absolute_deviation_energy_wh=150.0,
        deviation_percent=-75.0,
        percentage_status="available",
        direction="below_forecast",
        forecast_confidence=0.42,
        actual_confidence=1.0,
        forecast_evidence_ids=("solcast-anchor",),
        actual_evidence_ids=("goodwe-history",),
        forecast_conversion_method_version="solcast-average-kw-30m:v1",
        actual_conversion_method_version="goodwe-step-hold-energy:v1",
        evaluation_method_version="pv-energy-deviation:v1",
    )


def _observation():
    return build_pv_attenuation_observation(
        deviation=_deviation(),
        installation_scope_id="pv-installation-home",
        forecast_captured_at=CAPTURED,
        solar_azimuth_degrees=267.5,
        solar_elevation_degrees=8.25,
        sunset_at=SUNSET,
        forecast_mapping_version="solcast-combined-installation:v1",
        alignment_status="aligned",
        coverage_status="complete",
    )


def test_builds_unassessed_sun_relative_observation_without_policy() -> None:
    observation = _observation()

    assert observation.installation_scope_id == "pv-installation-home"
    assert observation.starts_at == START
    assert observation.ends_at == END
    assert observation.forecast_captured_at == CAPTURED
    assert observation.forecast_lower_energy_wh == 120.0
    assert observation.forecast_central_energy_wh == 200.0
    assert observation.forecast_upper_energy_wh == 300.0
    assert observation.forecast_confidence == 0.42
    assert observation.actual_energy_wh == 50.0
    assert observation.actual_confidence == 1.0
    assert observation.solar_azimuth_degrees == 267.5
    assert observation.solar_elevation_degrees == 8.25
    assert observation.minutes_from_sunset == -43.0
    assert observation.forecast_evidence_ids == ("solcast-anchor",)
    assert observation.actual_evidence_ids == ("goodwe-history",)
    assert observation.alignment_status == "aligned"
    assert observation.coverage_status == "complete"
    assert observation.eligibility_status == "unassessed"
    assert observation.eligibility_reason == "eligibility_not_assessed"
    assert observation.eligibility_method_version == "not_applied"
    assert observation.observation_method_version == (
        ATTENUATION_EVIDENCE_METHOD_VERSION
    )


def test_observation_identity_is_deterministic_and_context_sensitive() -> None:
    first = _observation()
    second = _observation()
    changed = build_pv_attenuation_observation(
        deviation=_deviation(),
        installation_scope_id="pv-installation-home",
        forecast_captured_at=CAPTURED,
        solar_azimuth_degrees=268.0,
        solar_elevation_degrees=8.25,
        sunset_at=SUNSET,
        forecast_mapping_version="solcast-combined-installation:v1",
        alignment_status="aligned",
        coverage_status="complete",
    )

    assert first.observation_id == second.observation_id
    assert first.observation_id.startswith("pv-attenuation-observation-")
    assert changed.observation_id != first.observation_id


def test_observation_remains_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        _observation().actual_energy_wh = 75.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("captured_at", "sunset_at", "message"),
    [
        (
            CAPTURED.replace(tzinfo=None),
            SUNSET,
            "forecast_captured_at must be timezone-aware",
        ),
        (
            CAPTURED,
            SUNSET.replace(tzinfo=None),
            "sunset_at must be timezone-aware",
        ),
    ],
)
def test_rejects_ambiguous_solar_timing(
    captured_at: datetime,
    sunset_at: datetime,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_pv_attenuation_observation(
            deviation=_deviation(),
            installation_scope_id="pv-installation-home",
            forecast_captured_at=captured_at,
            solar_azimuth_degrees=267.5,
            solar_elevation_degrees=8.25,
            sunset_at=sunset_at,
            forecast_mapping_version="solcast-combined-installation:v1",
            alignment_status="aligned",
            coverage_status="complete",
        )


def test_missing_original_forecast_range_is_visible_and_not_invented() -> None:
    with pytest.raises(
        ValueError,
        match="available original forecast range is required",
    ):
        build_pv_attenuation_observation(
            deviation=_deviation(
                lower=None,
                central=None,
                upper=None,
                range_status="unavailable",
            ),
            installation_scope_id="pv-installation-home",
            forecast_captured_at=CAPTURED,
            solar_azimuth_degrees=267.5,
            solar_elevation_degrees=8.25,
            sunset_at=SUNSET,
            forecast_mapping_version="solcast-combined-installation:v1",
            alignment_status="aligned",
            coverage_status="complete",
        )


def test_store_round_trips_complete_observation_and_deduplicates(tmp_path) -> None:
    store = PVAttenuationEvidenceStore(
        tmp_path / "pv-attenuation-observations.jsonl"
    )
    observation = _observation()

    assert store.append(observation) is True
    assert store.append(observation) is False
    assert store.load() == (observation,)


def test_store_skips_corrupt_or_unknown_schema_records(tmp_path) -> None:
    path = tmp_path / "pv-attenuation-observations.jsonl"
    path.write_text(
        '{"schema_version":999}\nnot-json\n',
        encoding="utf-8",
    )

    assert PVAttenuationEvidenceStore(path).load() == ()


def test_projection_exposes_complete_lineage_without_recalculation() -> None:
    fields = project_pv_attenuation_observation(_observation())

    assert fields == {
        "pv_attenuation_observation_status": "unassessed",
        "pv_attenuation_observer_only": True,
        "pv_attenuation_observation_id": _observation().observation_id,
        "pv_attenuation_installation_scope_id": "pv-installation-home",
        "pv_attenuation_starts_at": START.isoformat(),
        "pv_attenuation_ends_at": END.isoformat(),
        "pv_attenuation_forecast_captured_at": CAPTURED.isoformat(),
        "pv_attenuation_forecast_lower_energy_wh": 120.0,
        "pv_attenuation_forecast_central_energy_wh": 200.0,
        "pv_attenuation_forecast_upper_energy_wh": 300.0,
        "pv_attenuation_forecast_confidence": 0.42,
        "pv_attenuation_actual_energy_wh": 50.0,
        "pv_attenuation_actual_confidence": 1.0,
        "pv_attenuation_solar_azimuth_degrees": 267.5,
        "pv_attenuation_solar_elevation_degrees": 8.25,
        "pv_attenuation_minutes_from_sunset": -43.0,
        "pv_attenuation_alignment_status": "aligned",
        "pv_attenuation_coverage_status": "complete",
        "pv_attenuation_eligibility_reason": "eligibility_not_assessed",
        "pv_attenuation_forecast_evidence_ids": ["solcast-anchor"],
        "pv_attenuation_actual_evidence_ids": ["goodwe-history"],
        "pv_attenuation_forecast_mapping_version": (
            "solcast-combined-installation:v1"
        ),
        "pv_attenuation_forecast_conversion_method_version": (
            "solcast-average-kw-30m:v1"
        ),
        "pv_attenuation_actual_conversion_method_version": (
            "goodwe-step-hold-energy:v1"
        ),
        "pv_attenuation_observation_method_version": (
            ATTENUATION_EVIDENCE_METHOD_VERSION
        ),
        "pv_attenuation_eligibility_method_version": "not_applied",
    }
