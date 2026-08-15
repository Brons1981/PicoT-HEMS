"""Traceable actual-versus-forecast PV energy deviation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from picot.v2.contracts import PVEnergyTimelineInterval

EVALUATION_METHOD_VERSION = "pv-energy-deviation:v1"
RANGE_ASSESSMENT_METHOD_VERSION = "pv-forecast-range-assessment:v1"


@dataclass(frozen=True, slots=True)
class PVDeviationResult:
    deviation_id: str
    starts_at: datetime
    ends_at: datetime
    evaluated_at: datetime
    forecast_interval_id: str
    actual_interval_id: str
    forecast_energy_wh: float
    forecast_lower_energy_wh: float | None
    forecast_central_energy_wh: float | None
    forecast_upper_energy_wh: float | None
    forecast_range_status: str
    forecast_range_source_fields: tuple[str, ...]
    forecast_range_method_version: str | None
    range_assessment: str
    range_distance_wh: float | None
    range_assessment_method_version: str
    actual_energy_wh: float
    deviation_energy_wh: float
    absolute_deviation_energy_wh: float
    deviation_percent: float | None
    percentage_status: str
    direction: str
    forecast_confidence: float
    actual_confidence: float
    forecast_evidence_ids: tuple[str, ...]
    actual_evidence_ids: tuple[str, ...]
    forecast_conversion_method_version: str | None
    actual_conversion_method_version: str | None
    evaluation_method_version: str


def evaluate_pv_energy_deviation(
    *,
    forecast: PVEnergyTimelineInterval,
    actual: PVEnergyTimelineInterval,
    evaluated_at: datetime,
) -> PVDeviationResult:
    """Compare aligned energy intervals without applying policy."""
    if forecast.evidence_type != "FORECAST":
        raise ValueError("forecast interval must use FORECAST evidence")
    if actual.evidence_type != "ACTUAL":
        raise ValueError("actual interval must use ACTUAL evidence")
    if (
        forecast.starts_at != actual.starts_at
        or forecast.ends_at != actual.ends_at
    ):
        raise ValueError("interval boundaries must match")
    if (
        evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise ValueError("evaluated_at must be timezone-aware")
    if evaluated_at < actual.ends_at:
        raise ValueError("evaluated_at must not precede interval end")

    deviation_energy_wh = (
        actual.pv_energy_wh - forecast.pv_energy_wh
    )
    if forecast.pv_energy_wh == 0.0:
        if actual.pv_energy_wh == 0.0:
            deviation_percent = 0.0
            percentage_status = "available"
        else:
            deviation_percent = None
            percentage_status = "undefined_zero_forecast"
    else:
        deviation_percent = (
            deviation_energy_wh
            / forecast.pv_energy_wh
            * 100.0
        )
        percentage_status = "available"

    if deviation_energy_wh < 0.0:
        direction = "below_forecast"
    elif deviation_energy_wh > 0.0:
        direction = "above_forecast"
    else:
        direction = "matches_forecast"

    if forecast.forecast_range_status == "available":
        lower = forecast.forecast_lower_energy_wh
        upper = forecast.forecast_upper_energy_wh
        assert lower is not None
        assert upper is not None
        if actual.pv_energy_wh < lower:
            range_assessment = "below_range"
            range_distance_wh = lower - actual.pv_energy_wh
        elif actual.pv_energy_wh > upper:
            range_assessment = "above_range"
            range_distance_wh = actual.pv_energy_wh - upper
        else:
            range_assessment = "within_range"
            range_distance_wh = 0.0
    else:
        range_assessment = "unavailable"
        range_distance_wh = None

    seed = "|".join((
        forecast.interval_id,
        actual.interval_id,
        evaluated_at.isoformat(),
        str(forecast.pv_energy_wh),
        str(forecast.forecast_lower_energy_wh),
        str(forecast.forecast_upper_energy_wh),
        forecast.forecast_range_status,
        range_assessment,
        str(actual.pv_energy_wh),
        *forecast.forecast_evidence_ids,
        *actual.actual_evidence_ids,
    ))
    deviation_id = (
        "pv-deviation-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )

    return PVDeviationResult(
        deviation_id=deviation_id,
        starts_at=actual.starts_at,
        ends_at=actual.ends_at,
        evaluated_at=evaluated_at,
        forecast_interval_id=forecast.interval_id,
        actual_interval_id=actual.interval_id,
        forecast_energy_wh=forecast.pv_energy_wh,
        forecast_lower_energy_wh=(
            forecast.forecast_lower_energy_wh
        ),
        forecast_central_energy_wh=(
            forecast.forecast_central_energy_wh
        ),
        forecast_upper_energy_wh=(
            forecast.forecast_upper_energy_wh
        ),
        forecast_range_status=forecast.forecast_range_status,
        forecast_range_source_fields=(
            forecast.forecast_range_source_fields
        ),
        forecast_range_method_version=(
            forecast.forecast_range_method_version
        ),
        range_assessment=range_assessment,
        range_distance_wh=range_distance_wh,
        range_assessment_method_version=(
            RANGE_ASSESSMENT_METHOD_VERSION
        ),
        actual_energy_wh=actual.pv_energy_wh,
        deviation_energy_wh=deviation_energy_wh,
        absolute_deviation_energy_wh=abs(deviation_energy_wh),
        deviation_percent=deviation_percent,
        percentage_status=percentage_status,
        direction=direction,
        forecast_confidence=forecast.confidence,
        actual_confidence=actual.confidence,
        forecast_evidence_ids=forecast.forecast_evidence_ids,
        actual_evidence_ids=actual.actual_evidence_ids,
        forecast_conversion_method_version=(
            forecast.conversion_method_version
        ),
        actual_conversion_method_version=(
            actual.conversion_method_version
        ),
        evaluation_method_version=EVALUATION_METHOD_VERSION,
    )
