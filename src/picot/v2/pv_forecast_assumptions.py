"""Bounded future PV forecast-basis assumptions for Candidates."""

from __future__ import annotations

from hashlib import sha256

from picot.v2.contracts import (
    PlanningInputSnapshot,
    PVForecastAssumptionSet,
    PVForecastBasisAssumption,
    PVForecastBasisInterval,
)

ASSUMPTION_METHOD_VERSION = (
    "pv-forecast-basis-assumptions:future-intervals:v1"
)
MAXIMUM_ASSUMPTION_COUNT = 3
WHOLE_HOUSEHOLD_SCOPE = "whole_household_energy_path"


def _stable_id(prefix: str, seed: str) -> str:
    return (
        f"{prefix}-"
        f"{sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    )


def derive_pv_forecast_basis_assumptions(
    snapshot: PlanningInputSnapshot,
) -> PVForecastAssumptionSet:
    """Preserve at most lower/central/upper future PV assumptions."""
    timeline = snapshot.pv_energy_timeline
    future = tuple(
        interval
        for interval in (() if timeline is None else timeline.intervals)
        if (
            interval.evidence_type == "FORECAST"
            and interval.ends_at > snapshot.captured_at
            and (
                snapshot.horizon_end is None
                or interval.starts_at < snapshot.horizon_end
            )
        )
    )
    all_ranges_available = bool(future) and all(
        interval.forecast_range_status == "available"
        and interval.forecast_lower_energy_wh is not None
        and interval.forecast_upper_energy_wh is not None
        for interval in future
    )

    assumptions: list[PVForecastBasisAssumption] = []
    for basis in ("lower", "central", "upper"):
        available = bool(future) and (
            basis == "central" or all_ranges_available
        )
        if not future:
            unavailable_reason = "no_future_forecast_intervals"
        elif basis != "central" and not all_ranges_available:
            unavailable_reason = "forecast_range_unavailable"
        else:
            unavailable_reason = None

        assumption_intervals: list[PVForecastBasisInterval] = []
        if available:
            for source in future:
                starts_at = max(
                    source.starts_at,
                    snapshot.captured_at,
                )
                ends_at = (
                    min(source.ends_at, snapshot.horizon_end)
                    if snapshot.horizon_end is not None
                    else source.ends_at
                )
                if starts_at >= ends_at:
                    continue
                source_seconds = (
                    source.ends_at - source.starts_at
                ).total_seconds()
                selected_seconds = (
                    ends_at - starts_at
                ).total_seconds()
                if basis == "lower":
                    source_energy = source.forecast_lower_energy_wh
                elif basis == "upper":
                    source_energy = source.forecast_upper_energy_wh
                else:
                    source_energy = source.pv_energy_wh
                assert source_energy is not None
                selected_energy = (
                    source_energy
                    * selected_seconds
                    / source_seconds
                )
                assumption_intervals.append(
                    PVForecastBasisInterval(
                        source_interval_id=source.interval_id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        selected_energy_wh=selected_energy,
                        confidence=source.confidence,
                        forecast_evidence_ids=(
                            source.forecast_evidence_ids
                        ),
                        forecast_range_status=(
                            source.forecast_range_status
                        ),
                        forecast_range_method_version=(
                            source.forecast_range_method_version
                        ),
                        conversion_method_version=(
                            source.conversion_method_version
                        ),
                    )
                )

        assumption_id = _stable_id(
            "pv-forecast-assumption",
            "|".join(
                (
                    snapshot.snapshot_id,
                    basis,
                    ASSUMPTION_METHOD_VERSION,
                    *(
                        f"{item.source_interval_id}:"
                        f"{item.starts_at.isoformat()}:"
                        f"{item.ends_at.isoformat()}:"
                        f"{item.selected_energy_wh}"
                        for item in assumption_intervals
                    ),
                )
            ),
        )
        assumptions.append(
            PVForecastBasisAssumption(
                assumption_id=assumption_id,
                basis=basis,
                scope=WHOLE_HOUSEHOLD_SCOPE,
                status="available" if available else "unavailable",
                unavailable_reason=unavailable_reason,
                intervals=tuple(assumption_intervals),
                method_version=ASSUMPTION_METHOD_VERSION,
            )
        )

    assumption_set_id = _stable_id(
        "pv-forecast-assumption-set",
        "|".join(
            (
                snapshot.snapshot_id,
                ASSUMPTION_METHOD_VERSION,
                *(item.assumption_id for item in assumptions),
            )
        ),
    )
    return PVForecastAssumptionSet(
        assumption_set_id=assumption_set_id,
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        maximum_assumption_count=MAXIMUM_ASSUMPTION_COUNT,
        assumptions=tuple(assumptions),
        method_version=ASSUMPTION_METHOD_VERSION,
    )

