"""Measured-PV basis selection for the independent daily planners."""

from __future__ import annotations

from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

from picot.v2.contracts import PlanningInputSnapshot
from picot.v2.live_pv_actual import LivePVActualDiagnostics

METHOD_VERSION = "daily-measured-pv-basis:v2"
MINIMUM_ACTUAL_INTERVALS = 4
MINIMUM_CENTRAL_EVIDENCE_WH = 500.0


@dataclass(frozen=True, slots=True)
class DailyPVBasisDecision:
    basis: str
    reason: str
    tracking_ratio: float | None
    recent_tracking_ratio: float | None
    assessed_interval_count: int
    adjusted_interval_count: int
    evidence_id: str | None
    method_version: str = METHOD_VERSION


def apply_daily_measured_pv_basis(
    snapshot: PlanningInputSnapshot,
    *,
    diagnostics: LivePVActualDiagnostics | None,
    local_timezone: ZoneInfo,
) -> tuple[PlanningInputSnapshot, DailyPVBasisDecision]:
    """Plan from the lower/central midpoint and adapt today's basis to actuals.

    The returned snapshot is intended exclusively for EP/MEP. The canonical
    planner keeps the unmodified snapshot and therefore retains its existing
    conservative basis. Future dates remain on the midpoint; complete closed
    actual evidence may move only the remaining current day to lower or central.
    """

    decision = _select_basis(diagnostics)
    timeline = snapshot.pv_energy_timeline
    if timeline is None:
        return snapshot, decision

    local_date = snapshot.captured_at.astimezone(local_timezone).date()
    adjusted_count = 0
    adjusted_intervals = []
    for interval in timeline.intervals:
        is_remaining_forecast = (
            interval.ends_at > snapshot.captured_at
            and interval.evidence_type == "FORECAST"
            and interval.forecast_range_status == "available"
            and interval.forecast_lower_energy_wh is not None
            and interval.forecast_central_energy_wh is not None
        )
        if is_remaining_forecast:
            is_remaining_today = (
                interval.starts_at.astimezone(local_timezone).date() == local_date
            )
            midpoint_wh = (
                interval.forecast_lower_energy_wh
                + interval.forecast_central_energy_wh
            ) / 2.0
            selected_lower_wh = midpoint_wh
            if is_remaining_today and decision.basis == "lower":
                selected_lower_wh = interval.forecast_lower_energy_wh
            elif is_remaining_today and decision.basis == "central":
                selected_lower_wh = interval.forecast_central_energy_wh
            adjusted_intervals.append(
                replace(
                    interval,
                    forecast_lower_energy_wh=selected_lower_wh,
                )
            )
            adjusted_count += selected_lower_wh != interval.forecast_lower_energy_wh
        else:
            adjusted_intervals.append(interval)

    if adjusted_count == 0:
        return snapshot, replace(
            decision,
            reason=f"{decision.basis}_selected_no_adjustable_intervals",
        )
    return (
        replace(
            snapshot,
            pv_energy_timeline=replace(
                timeline,
                intervals=tuple(adjusted_intervals),
            ),
        ),
        replace(decision, adjusted_interval_count=adjusted_count),
    )


def _select_basis(
    diagnostics: LivePVActualDiagnostics | None,
) -> DailyPVBasisDecision:
    if diagnostics is None or diagnostics.cumulative_evidence is None:
        return _decision("midpoint", "actual_evidence_unavailable")
    evidence = diagnostics.cumulative_evidence
    if (
        evidence.coverage_status != "complete"
        or diagnostics.actual_interval_count != diagnostics.closed_forecast_count
    ):
        return _decision(
            "midpoint",
            "actual_coverage_incomplete",
            assessed=evidence.assessed_interval_count,
            evidence_id=evidence.evidence_id,
        )
    daylight = tuple(
        item
        for item in diagnostics.deviation_results
        if (item.forecast_central_energy_wh is not None and item.forecast_central_energy_wh > 0.0)
    )
    if len(daylight) < MINIMUM_ACTUAL_INTERVALS:
        return _decision(
            "midpoint",
            "actual_duration_insufficient",
            assessed=len(daylight),
            evidence_id=evidence.evidence_id,
        )
    if evidence.forecast_central_energy_wh < MINIMUM_CENTRAL_EVIDENCE_WH:
        return _decision(
            "midpoint",
            "actual_energy_evidence_insufficient",
            assessed=len(daylight),
            evidence_id=evidence.evidence_id,
        )

    central_wh = evidence.forecast_central_energy_wh
    lower_wh = evidence.forecast_lower_energy_wh
    if lower_wh is None:
        return _decision(
            "midpoint",
            "actual_forecast_range_unavailable",
            assessed=len(daylight),
            evidence_id=evidence.evidence_id,
        )
    midpoint_wh = (lower_wh + central_wh) / 2.0
    tracking_ratio = evidence.actual_energy_wh / central_wh
    recent = daylight[-MINIMUM_ACTUAL_INTERVALS:]
    recent_central_wh = sum(item.forecast_central_energy_wh or 0.0 for item in recent)
    recent_lower_wh = sum(item.forecast_lower_energy_wh or 0.0 for item in recent)
    recent_actual_wh = sum(item.actual_energy_wh for item in recent)
    recent_tracking_ratio = (
        recent_actual_wh / recent_central_wh
        if recent_central_wh > 0.0
        else None
    )
    recent_midpoint_wh = (recent_lower_wh + recent_central_wh) / 2.0
    if (
        evidence.actual_energy_wh < midpoint_wh
        or recent_actual_wh < recent_midpoint_wh
    ):
        return DailyPVBasisDecision(
            basis="lower",
            reason="actual_tracking_below_midpoint",
            tracking_ratio=tracking_ratio,
            recent_tracking_ratio=recent_tracking_ratio,
            assessed_interval_count=len(daylight),
            adjusted_interval_count=0,
            evidence_id=evidence.evidence_id,
        )
    basis = (
        "central"
        if evidence.actual_energy_wh >= central_wh
        and recent_actual_wh >= recent_central_wh
        else "midpoint"
    )
    return DailyPVBasisDecision(
        basis=basis,
        reason=(
            "actual_tracking_supports_central"
            if basis == "central"
            else "actual_tracking_supports_midpoint"
        ),
        tracking_ratio=tracking_ratio,
        recent_tracking_ratio=recent_tracking_ratio,
        assessed_interval_count=len(daylight),
        adjusted_interval_count=0,
        evidence_id=evidence.evidence_id,
    )


def _decision(
    basis: str,
    reason: str,
    *,
    assessed: int = 0,
    evidence_id: str | None = None,
) -> DailyPVBasisDecision:
    return DailyPVBasisDecision(
        basis=basis,
        reason=reason,
        tracking_ratio=None,
        recent_tracking_ratio=None,
        assessed_interval_count=assessed,
        adjusted_interval_count=0,
        evidence_id=evidence_id,
    )
