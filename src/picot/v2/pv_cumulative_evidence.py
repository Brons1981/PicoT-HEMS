"""Cumulative aligned closed-interval PV deviation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from picot.v2.pv_deviation import PVDeviationResult

CUMULATIVE_EVIDENCE_METHOD_VERSION = (
    "pv-cumulative-deviation:aligned-closed-intervals:v1"
)


@dataclass(frozen=True, slots=True)
class PVCumulativeEvidence:
    evidence_id: str
    coverage_status: str
    starts_at: datetime | None
    ends_at: datetime | None
    evaluated_at: datetime
    closed_interval_count: int
    assessed_interval_count: int
    gap_interval_count: int
    coverage_ratio: float | None
    forecast_central_energy_wh: float
    actual_energy_wh: float
    net_deviation_energy_wh: float
    absolute_net_deviation_energy_wh: float
    total_absolute_interval_deviation_energy_wh: float
    deviation_percent: float | None
    percentage_status: str
    forecast_lower_energy_wh: float | None
    forecast_upper_energy_wh: float | None
    forecast_range_status: str
    range_assessment: str
    range_distance_wh: float | None
    range_assessed_interval_count: int
    below_range_interval_count: int
    within_range_interval_count: int
    above_range_interval_count: int
    unavailable_range_interval_count: int
    interval_deviation_ids: tuple[str, ...]
    method_version: str


def build_pv_cumulative_evidence(
    deviation_results: tuple[PVDeviationResult, ...],
    *,
    closed_interval_count: int,
    evaluated_at: datetime,
) -> PVCumulativeEvidence:
    """Aggregate only aligned forecast/actual results without correction."""
    if closed_interval_count < 0:
        raise ValueError("closed_interval_count must not be negative")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    results = tuple(
        sorted(
            deviation_results,
            key=lambda result: (
                result.starts_at,
                result.ends_at,
                result.deviation_id,
            ),
        )
    )
    assessed_count = len(results)
    if assessed_count > closed_interval_count:
        raise ValueError(
            "assessed interval count must not exceed closed interval count"
        )

    gap_count = closed_interval_count - assessed_count
    if assessed_count == 0:
        coverage_status = "unavailable"
    elif gap_count:
        coverage_status = "partial"
    else:
        coverage_status = "complete"

    coverage_ratio = (
        assessed_count / closed_interval_count
        if closed_interval_count
        else None
    )
    starts_at = results[0].starts_at if results else None
    ends_at = results[-1].ends_at if results else None

    forecast_total = sum(
        result.forecast_energy_wh for result in results
    )
    actual_total = sum(result.actual_energy_wh for result in results)
    net_deviation = actual_total - forecast_total
    absolute_net_deviation = abs(net_deviation)
    total_absolute_interval_deviation = sum(
        result.absolute_deviation_energy_wh for result in results
    )

    if not results:
        deviation_percent = None
        percentage_status = "no_assessed_intervals"
    elif forecast_total == 0.0:
        if actual_total == 0.0:
            deviation_percent = 0.0
            percentage_status = "available"
        else:
            deviation_percent = None
            percentage_status = "undefined_zero_forecast"
    else:
        deviation_percent = net_deviation / forecast_total * 100.0
        percentage_status = "available"

    range_results = tuple(
        result
        for result in results
        if (
            result.forecast_range_status == "available"
            and result.forecast_lower_energy_wh is not None
            and result.forecast_upper_energy_wh is not None
        )
    )
    if results and len(range_results) == assessed_count:
        forecast_lower = sum(
            result.forecast_lower_energy_wh
            for result in range_results
            if result.forecast_lower_energy_wh is not None
        )
        forecast_upper = sum(
            result.forecast_upper_energy_wh
            for result in range_results
            if result.forecast_upper_energy_wh is not None
        )
        forecast_range_status = "available"
        if actual_total < forecast_lower:
            range_assessment = "below_range"
            range_distance = forecast_lower - actual_total
        elif actual_total > forecast_upper:
            range_assessment = "above_range"
            range_distance = actual_total - forecast_upper
        else:
            range_assessment = "within_range"
            range_distance = 0.0
    else:
        forecast_lower = None
        forecast_upper = None
        forecast_range_status = "unavailable"
        range_assessment = "unavailable"
        range_distance = None

    below_count = sum(
        result.range_assessment == "below_range" for result in results
    )
    within_count = sum(
        result.range_assessment == "within_range" for result in results
    )
    above_count = sum(
        result.range_assessment == "above_range" for result in results
    )
    unavailable_count = sum(
        result.range_assessment == "unavailable" for result in results
    )
    interval_deviation_ids = tuple(
        result.deviation_id for result in results
    )

    seed = "|".join(
        (
            str(closed_interval_count),
            evaluated_at.isoformat(),
            CUMULATIVE_EVIDENCE_METHOD_VERSION,
            *interval_deviation_ids,
        )
    )
    evidence_id = (
        "pv-cumulative-evidence-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )

    return PVCumulativeEvidence(
        evidence_id=evidence_id,
        coverage_status=coverage_status,
        starts_at=starts_at,
        ends_at=ends_at,
        evaluated_at=evaluated_at,
        closed_interval_count=closed_interval_count,
        assessed_interval_count=assessed_count,
        gap_interval_count=gap_count,
        coverage_ratio=coverage_ratio,
        forecast_central_energy_wh=forecast_total,
        actual_energy_wh=actual_total,
        net_deviation_energy_wh=net_deviation,
        absolute_net_deviation_energy_wh=absolute_net_deviation,
        total_absolute_interval_deviation_energy_wh=(
            total_absolute_interval_deviation
        ),
        deviation_percent=deviation_percent,
        percentage_status=percentage_status,
        forecast_lower_energy_wh=forecast_lower,
        forecast_upper_energy_wh=forecast_upper,
        forecast_range_status=forecast_range_status,
        range_assessment=range_assessment,
        range_distance_wh=range_distance,
        range_assessed_interval_count=len(range_results),
        below_range_interval_count=below_count,
        within_range_interval_count=within_count,
        above_range_interval_count=above_count,
        unavailable_range_interval_count=unavailable_count,
        interval_deviation_ids=interval_deviation_ids,
        method_version=CUMULATIVE_EVIDENCE_METHOD_VERSION,
    )
