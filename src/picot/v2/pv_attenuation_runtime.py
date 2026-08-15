"""Observer-only live projection for PV attenuation diagnostics."""

from __future__ import annotations

from typing import Any

from picot.v2.projection import Card, Projection
from picot.v2.pv_attenuation_range import (
    PVAttenuatedForecastRange,
    project_pv_attenuated_forecast_range,
)

ATTENUATION_RUNTIME_PROJECTION_METHOD_VERSION = (
    "pv-attenuation-runtime-projection:v1"
)


def project_live_pv_attenuation_ranges(
    ranges: tuple[PVAttenuatedForecastRange, ...],
) -> dict[str, Any]:
    """Project traceable ranges without selecting them for planning."""

    if not ranges:
        return {
            "pv_attenuation_runtime_status": "not_available",
            "pv_attenuation_runtime_unavailable_reason": (
                "no_derived_ranges"
            ),
            "pv_attenuation_runtime_observer_only": True,
            "pv_attenuation_runtime_interval_count": 0,
            "pv_attenuation_runtime_available_interval_count": 0,
            "pv_attenuation_runtime_unavailable_interval_count": 0,
            "pv_attenuation_runtime_original_central_total_wh": None,
            "pv_attenuation_runtime_corrected_central_total_wh": None,
            "pv_attenuation_runtime_correction_delta_wh": None,
            "pv_attenuation_runtime_profile_ids": [],
            "pv_attenuation_runtime_bucket_ids": [],
            "pv_attenuation_runtime_projection_method_version": (
                ATTENUATION_RUNTIME_PROJECTION_METHOD_VERSION
            ),
            "pv_attenuation_runtime_intervals": [],
        }

    available_count = sum(
        result.status == "available" for result in ranges
    )
    unavailable_count = len(ranges) - available_count
    if available_count == len(ranges):
        status = "available"
        unavailable_reason = None
    elif available_count:
        status = "partial"
        unavailable_reason = "one_or_more_ranges_unavailable"
    else:
        status = "unavailable"
        unavailable_reason = "all_ranges_unavailable"

    original_values = tuple(
        result.original_central_energy_wh for result in ranges
    )
    corrected_values = tuple(
        result.corrected_central_energy_wh for result in ranges
    )
    totals_available = all(
        value is not None
        for value in (*original_values, *corrected_values)
    )
    original_total = (
        sum(value for value in original_values if value is not None)
        if totals_available
        else None
    )
    corrected_total = (
        sum(value for value in corrected_values if value is not None)
        if totals_available
        else None
    )
    correction_delta = (
        corrected_total - original_total
        if original_total is not None and corrected_total is not None
        else None
    )

    return {
        "pv_attenuation_runtime_status": status,
        "pv_attenuation_runtime_unavailable_reason": unavailable_reason,
        "pv_attenuation_runtime_observer_only": True,
        "pv_attenuation_runtime_interval_count": len(ranges),
        "pv_attenuation_runtime_available_interval_count": (
            available_count
        ),
        "pv_attenuation_runtime_unavailable_interval_count": (
            unavailable_count
        ),
        "pv_attenuation_runtime_original_central_total_wh": (
            original_total
        ),
        "pv_attenuation_runtime_corrected_central_total_wh": (
            corrected_total
        ),
        "pv_attenuation_runtime_correction_delta_wh": correction_delta,
        "pv_attenuation_runtime_profile_ids": _unique_non_null(
            result.profile_id for result in ranges
        ),
        "pv_attenuation_runtime_bucket_ids": _unique_non_null(
            result.bucket_id for result in ranges
        ),
        "pv_attenuation_runtime_projection_method_version": (
            ATTENUATION_RUNTIME_PROJECTION_METHOD_VERSION
        ),
        "pv_attenuation_runtime_intervals": [
            project_pv_attenuated_forecast_range(result)
            for result in ranges
        ],
    }


def attach_pv_attenuation_runtime_diagnostics(
    projection: Projection,
    ranges: tuple[PVAttenuatedForecastRange, ...],
) -> Projection:
    """Attach diagnostics to card 1 while preserving cards 2 through 9."""

    first = projection.cards[0]
    enriched = Card(
        first.entity_id,
        first.state,
        first.attributes | project_live_pv_attenuation_ranges(ranges),
    )
    return Projection(
        cards=(enriched, *projection.cards[1:]),
        projection_ms=projection.projection_ms,
    )


def _unique_non_null(values: Any) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value is not None and value not in unique:
            unique.append(value)
    return unique
