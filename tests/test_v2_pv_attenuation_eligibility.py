from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from picot.v2.pv_attenuation_eligibility import (
    ELIGIBILITY_METHOD_VERSION,
    PVAttenuationEligibilityConfig,
    classify_pv_attenuation_observation,
)

from picot.v2.contracts import PVAttenuationObservation

BASE_START = datetime(2026, 8, 15, 17, 0, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)


def _observation(
    *,
    day_offset: int,
    position: str,
    actual_energy_wh: float,
    central_energy_wh: float = 200.0,
    forecast_confidence: float = 0.8,
    actual_confidence: float = 1.0,
    alignment_status: str = "aligned",
    coverage_status: str = "complete",
) -> PVAttenuationObservation:
    position_minutes = {
        "preceding": -30,
        "target": 0,
        "following": 30,
    }[position]
    starts_at = (
        BASE_START
        + timedelta(days=day_offset, minutes=position_minutes)
    )
    ends_at = starts_at + timedelta(minutes=30)
    sunset_at = (
        datetime(2026, 8, 15, 18, 30, tzinfo=UTC)
        + timedelta(days=day_offset)
    )
    midpoint = starts_at + timedelta(minutes=15)
    return PVAttenuationObservation(
        observation_id=f"observation-{day_offset}-{position}",
        installation_scope_id="pv-installation-home",
        starts_at=starts_at,
        ends_at=ends_at,
        forecast_captured_at=starts_at - timedelta(hours=6),
        forecast_lower_energy_wh=central_energy_wh * 0.6,
        forecast_central_energy_wh=central_energy_wh,
        forecast_upper_energy_wh=central_energy_wh * 1.4,
        forecast_confidence=forecast_confidence,
        actual_energy_wh=actual_energy_wh,
        actual_confidence=actual_confidence,
        solar_azimuth_degrees=260.0 + position_minutes / 10,
        solar_elevation_degrees=12.0 - position_minutes / 30,
        minutes_from_sunset=(
            midpoint - sunset_at
        ).total_seconds() / 60.0,
        forecast_evidence_ids=(f"forecast-{day_offset}-{position}",),
        actual_evidence_ids=(f"actual-{day_offset}-{position}",),
        forecast_mapping_version="solcast-combined-installation:v1",
        forecast_conversion_method_version="solcast-average-kw-30m:v1",
        actual_conversion_method_version="goodwe-step-hold-energy:v1",
        eligibility_status="unassessed",
        eligibility_reason="eligibility_not_assessed",
        eligibility_method_version="not_applied",
        alignment_status=alignment_status,
        coverage_status=coverage_status,
        observation_method_version="pv-attenuation-evidence-capture:v1",
    )


def _evidence_days() -> tuple[PVAttenuationObservation, ...]:
    observations: list[PVAttenuationObservation] = []
    for day_offset in (-2, -1, 0):
        observations.extend(
            (
                _observation(
                    day_offset=day_offset,
                    position="preceding",
                    actual_energy_wh=190.0,
                ),
                _observation(
                    day_offset=day_offset,
                    position="target",
                    actual_energy_wh=50.0,
                ),
                _observation(
                    day_offset=day_offset,
                    position="following",
                    actual_energy_wh=55.0,
                ),
            )
        )
    return tuple(observations)


def _config(**overrides: object) -> PVAttenuationEligibilityConfig:
    values: dict[str, object] = {
        "minimum_forecast_energy_wh": 100.0,
        "minimum_forecast_confidence": 0.3,
        "minimum_actual_confidence": 0.9,
        "maximum_attenuation_ratio": 0.7,
        "minimum_preceding_tracking_ratio": 0.8,
        "maximum_preceding_tracking_ratio": 1.2,
        "minimum_distinct_days": 3,
        "sunset_bucket_tolerance_minutes": 20.0,
        "maximum_evidence_age_days": 45,
        "configuration_version": "pv-attenuation-eligibility-config:v1",
    }
    values.update(overrides)
    return PVAttenuationEligibilityConfig(**values)


def _classify(
    observations: tuple[PVAttenuationObservation, ...],
    *,
    target_id: str = "observation-0-target",
    config: PVAttenuationEligibilityConfig | None = None,
) -> PVAttenuationObservation:
    return classify_pv_attenuation_observation(
        target_observation_id=target_id,
        observations=observations,
        evaluated_at=EVALUATED_AT,
        config=config or _config(),
    )


def test_config_is_immutable_and_explicitly_versioned() -> None:
    config = _config()

    assert config.configuration_version == (
        "pv-attenuation-eligibility-config:v1"
    )
    with pytest.raises(FrozenInstanceError):
        config.minimum_distinct_days = 1  # type: ignore[misc]


def test_recurring_continuous_signal_becomes_eligible() -> None:
    original = next(
        item
        for item in _evidence_days()
        if item.observation_id == "observation-0-target"
    )
    classified = _classify(_evidence_days())

    assert classified.observation_id == original.observation_id
    assert classified.forecast_central_energy_wh == (
        original.forecast_central_energy_wh
    )
    assert classified.actual_energy_wh == original.actual_energy_wh
    assert classified.forecast_evidence_ids == (
        original.forecast_evidence_ids
    )
    assert classified.actual_evidence_ids == original.actual_evidence_ids
    assert classified.eligibility_status == "eligible"
    assert classified.eligibility_reason is None
    assert classified.eligibility_method_version == (
        f"{ELIGIBILITY_METHOD_VERSION}:"
        "pv-attenuation-eligibility-config:v1"
    )


@pytest.mark.parametrize(
    ("replacement", "reason"),
    (
        (
            {"alignment_status": "unaligned"},
            "interval_unaligned",
        ),
        (
            {"coverage_status": "partial"},
            "actual_coverage_incomplete",
        ),
        (
            {"central_energy_wh": 50.0},
            "forecast_below_energy_floor",
        ),
        (
            {"forecast_confidence": 0.2},
            "forecast_confidence_below_minimum",
        ),
        (
            {"actual_confidence": 0.5},
            "actual_confidence_below_minimum",
        ),
        (
            {"actual_energy_wh": 180.0},
            "no_attenuation_signal",
        ),
    ),
)
def test_target_quality_rejections_are_visible_and_prioritised(
    replacement: dict[str, object],
    reason: str,
) -> None:
    observations = list(_evidence_days())
    index = next(
        index
        for index, item in enumerate(observations)
        if item.observation_id == "observation-0-target"
    )
    observations[index] = _observation(
        day_offset=0,
        position="target",
        actual_energy_wh=float(
            replacement.get("actual_energy_wh", 50.0)
        ),
        central_energy_wh=float(
            replacement.get("central_energy_wh", 200.0)
        ),
        forecast_confidence=float(
            replacement.get("forecast_confidence", 0.8)
        ),
        actual_confidence=float(
            replacement.get("actual_confidence", 1.0)
        ),
        alignment_status=str(
            replacement.get("alignment_status", "aligned")
        ),
        coverage_status=str(
            replacement.get("coverage_status", "complete")
        ),
    )

    classified = _classify(tuple(observations))

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == reason


def test_requires_forecast_tracking_immediately_before_window() -> None:
    observations = tuple(
        (
            replace(item, actual_energy_wh=80.0)
            if item.observation_id == "observation-0-preceding"
            else item
        )
        for item in _evidence_days()
    )

    classified = _classify(observations)

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == (
        "forecast_not_tracked_before_window"
    )


def test_requires_contiguous_neighbouring_attenuation() -> None:
    observations = tuple(
        (
            replace(item, actual_energy_wh=190.0)
            if item.observation_id == "observation-0-following"
            else item
        )
        for item in _evidence_days()
    )

    classified = _classify(observations)

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == (
        "attenuation_not_continuous"
    )


def test_requires_recurrence_across_distinct_days() -> None:
    observations = tuple(
        item
        for item in _evidence_days()
        if not item.observation_id.startswith("observation--2-")
    )

    classified = _classify(observations)

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == (
        "insufficient_distinct_day_recurrence"
    )


def test_stale_evidence_is_rejected_without_hidden_reuse() -> None:
    classified = classify_pv_attenuation_observation(
        target_observation_id="observation-0-target",
        observations=_evidence_days(),
        evaluated_at=EVALUATED_AT + timedelta(days=60),
        config=_config(),
    )

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == "evidence_stale"


def test_other_installation_scope_cannot_supply_recurrence() -> None:
    unrelated = tuple(
        replace(item, installation_scope_id="other-installation")
        for item in _evidence_days()
        if item.observation_id.startswith("observation--2-")
    )
    observations = tuple(
        item
        for item in _evidence_days()
        if not item.observation_id.startswith("observation--2-")
    ) + unrelated

    classified = _classify(observations)

    assert classified.eligibility_status == "rejected"
    assert classified.eligibility_reason == (
        "insufficient_distinct_day_recurrence"
    )
