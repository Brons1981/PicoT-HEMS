from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from picot.v2.contracts import (
    PVAttenuationObservation,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.pv_attenuation_aggregation import (
    PVAttenuationAggregationConfig,
)
from picot.v2.pv_attenuation_eligibility import (
    PVAttenuationEligibilityConfig,
)
from picot.v2.pv_attenuation_evidence import PVAttenuationEvidenceStore
from picot.v2.pv_attenuation_runtime_derivation import (
    derive_live_pv_attenuation_ranges,
)
from picot.v2.pv_solar_history import (
    SOLAR_HISTORY_METHOD_VERSION,
    SolarContextObservation,
    SolarHistoryReadResult,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
EVALUATED_AT = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
BASE_START = datetime(2026, 8, 13, 17, 0, tzinfo=UTC)
INSTALLATION_SCOPE_ID = "pv-installation-home"


def _learning_module():
    return import_module("picot.v2.pv_attenuation_learning")


def _interval_id(day_offset: int, position: str) -> str:
    return f"pv-{day_offset}-{position}"


def _starts_at(day_offset: int, position: str) -> datetime:
    position_minutes = {
        "preceding": -30,
        "target": 0,
        "following": 30,
    }[position]
    return BASE_START + timedelta(
        days=day_offset,
        minutes=position_minutes,
    )


def _forecast(
    day_offset: int,
    position: str,
    *,
    central_energy_wh: float = 200.0,
) -> PVEnergyTimelineInterval:
    starts_at = _starts_at(day_offset, position)
    return PVEnergyTimelineInterval(
        interval_id=_interval_id(day_offset, position),
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=central_energy_wh,
        evidence_type="FORECAST",
        confidence=0.8,
        actual_evidence_ids=(),
        forecast_evidence_ids=(
            f"solcast-{day_offset}-{position}",
        ),
        conversion_method_version=(
            "solcast-detailed-forecast-average-kw-30m:v1"
        ),
        forecast_lower_energy_wh=central_energy_wh * 0.6,
        forecast_central_energy_wh=central_energy_wh,
        forecast_upper_energy_wh=central_energy_wh * 1.4,
        forecast_range_status="available",
        forecast_range_source_fields=(
            "pv_estimate10",
            "pv_estimate",
            "pv_estimate90",
        ),
        forecast_range_method_version=(
            "solcast-pv-estimate-range-average-kw-30m:v1"
        ),
    )


def _actual(
    day_offset: int,
    position: str,
    *,
    ratio: float,
) -> PVEnergyTimelineInterval:
    starts_at = _starts_at(day_offset, position)
    return PVEnergyTimelineInterval(
        interval_id=f"actual-{_interval_id(day_offset, position)}",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        pv_energy_wh=200.0 * ratio,
        evidence_type="ACTUAL",
        confidence=1.0,
        actual_evidence_ids=(
            f"goodwe-{day_offset}-{position}",
        ),
        forecast_evidence_ids=(),
        conversion_method_version=(
            "goodwe-state-transition-step-hold-energy:v1"
        ),
    )


def _forecast_timeline() -> PVEnergyTimeline:
    intervals = tuple(
        _forecast(day_offset, position)
        for day_offset in (-2, -1, 0)
        for position in ("preceding", "target", "following")
    )
    return PVEnergyTimeline(
        timeline_id="forecast-basis-three-days",
        run_id="forecast-capture-run",
        snapshot_id="forecast-capture-snapshot",
        intervals=intervals,
    )


def _actual_intervals() -> tuple[PVEnergyTimelineInterval, ...]:
    target_ratios = {-2: 0.4, -1: 0.5, 0: 0.6}
    return tuple(
        _actual(
            day_offset,
            position,
            ratio=(
                0.95
                if position == "preceding"
                else target_ratios[day_offset]
                if position == "target"
                else min(target_ratios[day_offset] + 0.05, 0.7)
            ),
        )
        for day_offset in (-2, -1, 0)
        for position in ("preceding", "target", "following")
    )


def _solar_observations(
    *,
    night_target: tuple[int, str] | None = None,
) -> tuple[SolarContextObservation, ...]:
    observations = []
    for day_offset in (-2, -1, 0):
        sunset_at = datetime(
            2026,
            8,
            13 + (day_offset + 2),
            18,
            30,
            tzinfo=UTC,
        )
        for position in ("preceding", "target", "following"):
            starts_at = _starts_at(day_offset, position)
            midpoint = starts_at + timedelta(minutes=15)
            observations.append(
                SolarContextObservation(
                    evidence_id=(
                        f"solar-{day_offset}-{position}"
                    ),
                    sampled_at=midpoint - timedelta(minutes=5),
                    solar_azimuth_degrees=265.0,
                    solar_elevation_degrees=(
                        0.0
                        if night_target == (day_offset, position)
                        else 9.0
                    ),
                    sunset_at=sunset_at.astimezone(AMSTERDAM),
                )
            )
    return tuple(observations)


class RecordingSolarHistoryReader:
    def __init__(
        self,
        observations: tuple[SolarContextObservation, ...],
    ) -> None:
        self.observations = observations
        self.calls: list[
            tuple[datetime, datetime, object]
        ] = []

    def __call__(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        local_timezone: object,
    ) -> SolarHistoryReadResult:
        self.calls.append((starts_at, ends_at, local_timezone))
        return SolarHistoryReadResult(
            source_entity_id="sun.sun",
            starts_at=starts_at,
            ends_at=ends_at,
            status="available",
            error=None,
            observations=self.observations,
            method_version=SOLAR_HISTORY_METHOD_VERSION,
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


def _runtime(
    tmp_path: Path,
    reader: RecordingSolarHistoryReader,
):
    module = _learning_module()
    return module.ObserverOnlyPVAttenuationLearningRuntime(
        forecast_basis_path=tmp_path / "forecast-basis.jsonl",
        evidence_store=PVAttenuationEvidenceStore(
            tmp_path / "attenuation-evidence.jsonl"
        ),
        solar_history_reader=reader,
        installation_scope_id=INSTALLATION_SCOPE_ID,
        local_timezone=AMSTERDAM,
        maximum_solar_age_seconds=900,
        forecast_mapping_version=(
            "solcast-combined-installation:v1"
        ),
        eligibility_config=_eligibility_config(),
        aggregation_config=_aggregation_config(),
    )


def test_complete_observer_only_learning_chain_builds_traceable_profile(
    tmp_path: Path,
) -> None:
    module = _learning_module()
    reader = RecordingSolarHistoryReader(_solar_observations())
    runtime = _runtime(tmp_path, reader)
    timeline = _forecast_timeline()
    captured_at = timeline.intervals[0].starts_at - timedelta(hours=6)

    assert runtime.capture_forecast_basis(
        timeline=timeline,
        captured_at=captured_at,
    ) == 9

    changed_first = replace(
        timeline.intervals[0],
        pv_energy_wh=1000.0,
        forecast_lower_energy_wh=600.0,
        forecast_central_energy_wh=1000.0,
        forecast_upper_energy_wh=1400.0,
    )
    changed_timeline = replace(
        timeline,
        intervals=(changed_first, *timeline.intervals[1:]),
    )
    persisted_basis = (
        tmp_path / "forecast-basis.jsonl"
    ).read_text(encoding="utf-8")

    assert runtime.capture_forecast_basis(
        timeline=changed_timeline,
        captured_at=captured_at + timedelta(hours=1),
    ) == 0
    assert (
        tmp_path / "forecast-basis.jsonl"
    ).read_text(encoding="utf-8") == persisted_basis

    result = runtime.evaluate_closed_actuals(
        actual_intervals=_actual_intervals(),
        evaluated_at=EVALUATED_AT,
    )

    assert len(reader.calls) == 1
    first_midpoint = timeline.intervals[0].starts_at + timedelta(
        minutes=15
    )
    last_midpoint = timeline.intervals[-1].starts_at + timedelta(
        minutes=15
    )
    assert reader.calls[0] == (
        first_midpoint - timedelta(seconds=900),
        last_midpoint,
        AMSTERDAM,
    )
    assert result.status == "profile_available"
    assert result.observer_only is True
    assert result.cache_hit is False
    assert result.closed_actual_interval_count == 9
    assert result.archived_forecast_match_count == 9
    assert result.solar_aligned_count == 9
    assert result.persisted_observation_count == 9
    assert result.profile.status == "available"
    assert result.method_version == (
        module.ATTENUATION_LEARNING_METHOD_VERSION
    )

    target_bucket = next(
        bucket
        for bucket in result.profile.buckets
        if bucket.sunset_offset_starts_minutes == -90.0
    )
    assert target_bucket.attenuation_factor == pytest.approx(0.5)
    assert target_bucket.distinct_day_count == 3

    stored = PVAttenuationEvidenceStore(
        tmp_path / "attenuation-evidence.jsonl"
    ).load()
    target = next(
        observation
        for observation in stored
        if observation.starts_at == _starts_at(0, "target")
    )
    assert target.solar_evidence_id == "solar-0-target"
    assert target.solar_observed_at == (
        target.starts_at + timedelta(minutes=10)
    )
    assert target.sunset_at == datetime(
        2026,
        8,
        15,
        20,
        30,
        tzinfo=AMSTERDAM,
    )
    assert target.solar_alignment_method_version == (
        "pv-solar-context-alignment:v1"
    )
    assert target.forecast_captured_at == captured_at

    second = runtime.evaluate_closed_actuals(
        actual_intervals=_actual_intervals(),
        evaluated_at=EVALUATED_AT,
    )
    assert second.cache_hit is True
    assert second.persisted_observation_count == 0
    assert len(reader.calls) == 1

    projection = module.project_pv_attenuation_learning_result(second)
    assert projection["pv_attenuation_learning_observer_only"] is True
    assert projection["pv_attenuation_learning_status"] == (
        "profile_available"
    )
    assert projection["pv_attenuation_learning_cache_hit"] is True
    assert projection["pv_attenuation_learning_profile_status"] == (
        "available"
    )

    future = _forecast(1, "target")
    ranges = derive_live_pv_attenuation_ranges(
        installation_scope_id=INSTALLATION_SCOPE_ID,
        timeline=PVEnergyTimeline(
            timeline_id="future",
            run_id="future-run",
            snapshot_id="future-snapshot",
            intervals=(future,),
        ),
        profile=result.profile,
        minutes_from_sunset_by_interval_id={
            future.interval_id: -75.0,
        },
        projected_at=EVALUATED_AT,
    )
    assert ranges[0].corrected_central_energy_wh == pytest.approx(100.0)


def test_nighttime_interval_is_persisted_for_audit_but_never_learned(
    tmp_path: Path,
) -> None:
    reader = RecordingSolarHistoryReader(
        _solar_observations(night_target=(0, "target"))
    )
    runtime = _runtime(tmp_path, reader)
    timeline = _forecast_timeline()
    runtime.capture_forecast_basis(
        timeline=timeline,
        captured_at=timeline.intervals[0].starts_at
        - timedelta(hours=6),
    )

    result = runtime.evaluate_closed_actuals(
        actual_intervals=_actual_intervals(),
        evaluated_at=EVALUATED_AT,
    )

    stored: tuple[PVAttenuationObservation, ...] = (
        PVAttenuationEvidenceStore(
            tmp_path / "attenuation-evidence.jsonl"
        ).load()
    )
    night = next(
        observation
        for observation in stored
        if observation.starts_at == _starts_at(0, "target")
    )
    assert night.eligibility_status == "rejected"
    assert night.eligibility_reason == "sun_below_horizon"
    assert result.rejection_reasons["sun_below_horizon"] == 1
    assert result.profile.status == "unavailable"
    target_bucket = next(
        bucket
        for bucket in result.profile.buckets
        if bucket.sunset_offset_starts_minutes == -90.0
    )
    assert target_bucket.attenuation_factor == 1.0
