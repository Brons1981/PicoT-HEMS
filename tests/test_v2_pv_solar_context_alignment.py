from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from picot.v2.pv_solar_context_alignment import (
    SOLAR_CONTEXT_ALIGNMENT_METHOD_VERSION,
    align_solar_context_to_deviation,
)
from picot.v2.pv_deviation import PVDeviationResult
from picot.v2.pv_solar_history import SolarContextObservation

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
STARTS_AT = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)
ENDS_AT = datetime(2026, 8, 16, 18, 30, tzinfo=UTC)
MIDPOINT = datetime(2026, 8, 16, 18, 15, tzinfo=UTC)


def _deviation() -> PVDeviationResult:
    return cast(
        PVDeviationResult,
        SimpleNamespace(
            deviation_id="pv-deviation-closed-interval",
            starts_at=STARTS_AT,
            ends_at=ENDS_AT,
            evaluated_at=ENDS_AT,
        ),
    )


def _solar_observation(
    *,
    evidence_id: str,
    sampled_at: datetime,
    elevation: float,
    sunset_at: datetime = datetime(
        2026,
        8,
        16,
        20,
        55,
        tzinfo=AMSTERDAM,
    ),
) -> SolarContextObservation:
    return SolarContextObservation(
        evidence_id=evidence_id,
        sampled_at=sampled_at,
        solar_azimuth_degrees=274.0,
        solar_elevation_degrees=elevation,
        sunset_at=sunset_at,
    )


def test_latest_observation_at_or_before_midpoint_is_selected_without_interpolation() -> None:
    earlier = _solar_observation(
        evidence_id="solar-earlier",
        sampled_at=MIDPOINT - timedelta(minutes=20),
        elevation=7.0,
    )
    selected = _solar_observation(
        evidence_id="solar-selected",
        sampled_at=MIDPOINT - timedelta(minutes=10),
        elevation=5.0,
    )
    future = _solar_observation(
        evidence_id="solar-future",
        sampled_at=MIDPOINT + timedelta(minutes=1),
        elevation=4.0,
    )

    result = align_solar_context_to_deviation(
        deviation=_deviation(),
        observations=(future, earlier, selected),
        local_timezone=AMSTERDAM,
        maximum_age_seconds=900,
    )

    assert result.deviation_id == "pv-deviation-closed-interval"
    assert result.interval_midpoint == MIDPOINT
    assert result.status == "aligned"
    assert result.reason is None
    assert result.solar_observation_evidence_id == "solar-selected"
    assert result.solar_observation_sampled_at == selected.sampled_at
    assert result.solar_azimuth_degrees == 274.0
    assert result.solar_elevation_degrees == 5.0
    assert result.sunset_at == selected.sunset_at
    assert result.observation_age_seconds == 600.0
    assert result.method_version == SOLAR_CONTEXT_ALIGNMENT_METHOD_VERSION
    assert result.method_version == "pv-solar-context-alignment:v1"


def test_future_only_observation_is_explicitly_unavailable() -> None:
    future = _solar_observation(
        evidence_id="solar-future",
        sampled_at=MIDPOINT + timedelta(seconds=1),
        elevation=4.0,
    )

    result = align_solar_context_to_deviation(
        deviation=_deviation(),
        observations=(future,),
        local_timezone=AMSTERDAM,
        maximum_age_seconds=900,
    )

    assert result.status == "unavailable"
    assert result.reason == "no_observation_at_or_before_midpoint"
    assert result.solar_observation_evidence_id is None


def test_latest_past_observation_outside_freshness_bound_is_explicitly_stale() -> None:
    stale = _solar_observation(
        evidence_id="solar-stale",
        sampled_at=MIDPOINT - timedelta(minutes=16),
        elevation=8.0,
    )

    result = align_solar_context_to_deviation(
        deviation=_deviation(),
        observations=(stale,),
        local_timezone=AMSTERDAM,
        maximum_age_seconds=900,
    )

    assert result.status == "unavailable"
    assert result.reason == "observation_stale"
    assert result.solar_observation_evidence_id == "solar-stale"
    assert result.observation_age_seconds == 960.0


def test_sunset_must_match_interval_midpoint_local_date() -> None:
    wrong_date = _solar_observation(
        evidence_id="solar-wrong-sunset-date",
        sampled_at=MIDPOINT - timedelta(minutes=5),
        elevation=5.0,
        sunset_at=datetime(
            2026,
            8,
            17,
            20,
            53,
            tzinfo=AMSTERDAM,
        ),
    )

    result = align_solar_context_to_deviation(
        deviation=_deviation(),
        observations=(wrong_date,),
        local_timezone=AMSTERDAM,
        maximum_age_seconds=900,
    )

    assert result.status == "unavailable"
    assert result.reason == "sunset_local_date_mismatch"
    assert result.solar_observation_evidence_id == (
        "solar-wrong-sunset-date"
    )


@pytest.mark.parametrize("maximum_age_seconds", (0, -1))
def test_freshness_bound_must_be_positive(
    maximum_age_seconds: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="maximum_age_seconds must be positive",
    ):
        align_solar_context_to_deviation(
            deviation=_deviation(),
            observations=(),
            local_timezone=AMSTERDAM,
            maximum_age_seconds=maximum_age_seconds,
        )
