"""ADR-conformant Price Driven v2 runtime bridge.

Price Driven v2 now uses the canonical Planning Input Snapshot -> Opportunity
Engine -> Candidate Engine path. Price opportunities remain evidence only.
Cost-first control is intentionally not dispatched while ADR-031 excludes it for
lack of an accepted energy-target/projected-state/power-allocation contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from picot.addon import runtime
from picot.addon.canonical_price_pipeline import run_canonical_price_pipeline
from picot.domain.candidate import CandidateSet
from picot.domain.forecast import ForecastSeries
from picot.domain.home_assistant import HomeAssistantDispatchMode
from picot.domain.opportunity import (
    Opportunity,
    OpportunityKind,
    OpportunityMetricKind,
    OpportunitySet,
)

PRICE_ENTRY_DELAY_MINUTES = (15, 30, 45, 60)
PRICE_KINDS = {
    OpportunityKind.NEGATIVE_PRICE_WINDOW,
    OpportunityKind.LOWEST_PRICE_WINDOW,
    OpportunityKind.HIGH_EXPORT_VALUE_WINDOW,
}


def _metric_value(opportunity: Opportunity, kind: OpportunityMetricKind) -> float | None:
    for metric in opportunity.metrics:
        if metric.kind is kind:
            return metric.value
    return None


def _serialize_opportunities(opportunity_set: OpportunitySet) -> list[dict[str, object]]:
    """Serialize objective canonical price opportunities without inventing rank."""

    serialized: list[dict[str, object]] = []
    for opportunity in opportunity_set.opportunities:
        if opportunity.kind not in PRICE_KINDS:
            continue
        serialized.append(
            {
                "opportunity_id": opportunity.opportunity_id,
                "kind": opportunity.kind.value,
                "starts_at": opportunity.starts_at.isoformat(),
                "ends_at": opportunity.ends_at.isoformat(),
                "confidence": opportunity.confidence,
                "average_price_eur_per_kwh": _metric_value(
                    opportunity,
                    OpportunityMetricKind.AVERAGE_ENERGY_PRICE_EUR_PER_KWH,
                ),
                "minimum_price_eur_per_kwh": _metric_value(
                    opportunity,
                    OpportunityMetricKind.MINIMUM_ENERGY_PRICE_EUR_PER_KWH,
                ),
                "maximum_price_eur_per_kwh": _metric_value(
                    opportunity,
                    OpportunityMetricKind.MAXIMUM_ENERGY_PRICE_EUR_PER_KWH,
                ),
                "reference_price_eur_per_kwh": _metric_value(
                    opportunity,
                    OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH,
                ),
                "boundary_price_eur_per_kwh": _metric_value(
                    opportunity,
                    OpportunityMetricKind.PRICE_BOUNDARY_EUR_PER_KWH,
                ),
                "duration_seconds": _metric_value(
                    opportunity,
                    OpportunityMetricKind.DURATION_SECONDS,
                ),
                "source_interval_count": _metric_value(
                    opportunity,
                    OpportunityMetricKind.SOURCE_INTERVAL_COUNT,
                ),
                "bridged_interval_count": _metric_value(
                    opportunity,
                    OpportunityMetricKind.BRIDGED_INTERVAL_COUNT,
                ),
            }
        )
    return serialized


def _serialize_candidate_exclusions(candidates: CandidateSet) -> list[dict[str, object]]:
    return [
        {
            "family": exclusion.family.value,
            "kind": exclusion.kind.value,
            "reason": exclusion.reason,
            "source_ids": list(exclusion.source_ids),
        }
        for exclusion in candidates.exclusions
    ]


def _diagnostic_low_price_opportunity(
    opportunity_set: OpportunitySet,
    *,
    evaluated_at: datetime,
) -> tuple[Opportunity | None, str]:
    """Choose only a diagnostic current/next/completed low-price window.

    This chronological diagnostic selection is not a planner rank and is never
    passed back into Candidate Generation or execution.
    """

    low_windows = tuple(
        sorted(
            (
                item
                for item in opportunity_set.opportunities
                if item.kind is OpportunityKind.LOWEST_PRICE_WINDOW
            ),
            key=lambda item: (item.starts_at, item.opportunity_id),
        )
    )
    active = next(
        (
            item
            for item in low_windows
            if item.starts_at <= evaluated_at < item.ends_at
        ),
        None,
    )
    if active is not None:
        return active, "active"

    future = tuple(item for item in low_windows if item.starts_at > evaluated_at)
    if future:
        return future[0], "next"

    completed = tuple(item for item in low_windows if item.ends_at <= evaluated_at)
    if completed:
        return max(completed, key=lambda item: item.ends_at), "most_recent_completed"
    return None, "none"


def _price_entry_observation(
    opportunity_set: OpportunitySet,
    forecast: ForecastSeries,
    *,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Keep the old entry-price forensic comparison observation-only.

    The value is retained only for historical comparison while Price Driven is
    migrated. It is explicitly not the selected/best start and never enters the
    canonical planner as input.
    """

    opportunity, opportunity_context = _diagnostic_low_price_opportunity(
        opportunity_set,
        evaluated_at=evaluated_at,
    )
    if opportunity is None:
        return {
            "price_entry_observation_status": "no_opportunity",
            "price_entry_observation_only": True,
            "price_entry_replan_input": False,
            "price_entry_opportunity_context": opportunity_context,
            "price_entry_limitation": (
                "No low-price opportunity is available for the legacy entry comparison."
            ),
        }

    points = tuple(
        point
        for point in forecast.points
        if opportunity.starts_at <= point.starts_at < opportunity.ends_at
    )
    if not points:
        return {
            "price_entry_observation_status": "insufficient_price_points",
            "price_entry_observation_only": True,
            "price_entry_replan_input": False,
            "price_entry_opportunity_context": opportunity_context,
            "price_entry_opportunity_id": opportunity.opportunity_id,
            "price_entry_opportunity_starts_at": opportunity.starts_at.isoformat(),
            "price_entry_opportunity_ends_at": opportunity.ends_at.isoformat(),
            "price_entry_limitation": (
                "The opportunity exists, but matching forecast points were unavailable."
            ),
        }

    entry = points[0]
    later_points = points[1:]
    lowest_later = (
        min(later_points, key=lambda point: (point.value, point.starts_at))
        if later_points
        else None
    )
    cheaper_later = lowest_later is not None and lowest_later.value < entry.value

    alternatives: list[dict[str, object]] = []
    for delay_minutes in PRICE_ENTRY_DELAY_MINUTES:
        starts_at = opportunity.starts_at + timedelta(minutes=delay_minutes)
        candidate = next((point for point in points if point.starts_at == starts_at), None)
        if candidate is None:
            alternatives.append(
                {
                    "delay_minutes": delay_minutes,
                    "status": "not_available",
                    "starts_at": starts_at.isoformat(),
                }
            )
            continue
        alternatives.append(
            {
                "delay_minutes": delay_minutes,
                "status": "available",
                "starts_at": candidate.starts_at.isoformat(),
                "price_eur_per_kwh": candidate.value,
                "delta_vs_entry_eur_per_kwh": candidate.value - entry.value,
                "cheaper_than_entry": candidate.value < entry.value,
            }
        )

    result: dict[str, object] = {
        "price_entry_observation_status": (
            "lower_later_price_exists" if cheaper_later else "entry_is_lowest_so_far"
        ),
        "price_entry_observation_only": True,
        "price_entry_replan_input": False,
        "price_entry_opportunity_context": opportunity_context,
        "price_entry_opportunity_id": opportunity.opportunity_id,
        "price_entry_opportunity_starts_at": opportunity.starts_at.isoformat(),
        "price_entry_opportunity_ends_at": opportunity.ends_at.isoformat(),
        "price_entry_reference_starts_at": entry.starts_at.isoformat(),
        "price_entry_reference_price_eur_per_kwh": entry.value,
        "price_entry_better_later_price_exists": cheaper_later,
        "price_entry_alternatives": alternatives,
        "price_entry_limitation": (
            "Legacy observation only. The lowest later quarter-hour is not a best start "
            "and is not used by the canonical planner."
        ),
    }
    if lowest_later is not None:
        result.update(
            {
                "price_entry_best_later_starts_at": lowest_later.starts_at.isoformat(),
                "price_entry_best_later_price_eur_per_kwh": lowest_later.value,
                "price_entry_best_later_saving_eur_per_kwh": entry.value - lowest_later.value,
            }
        )
    return result


def _current_price(forecast: ForecastSeries, *, evaluated_at: datetime) -> float | str:
    point = next(
        (
            item
            for item in forecast.points
            if item.starts_at <= evaluated_at < item.ends_at
        ),
        None,
    )
    return point.value if point is not None else "unknown"


def run_planner_once(
    options: dict[str, Any],
    token: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run Price Driven v2 through the canonical planner path up to Candidates."""

    evaluated_at = now or datetime.now(runtime.LOCAL_TIMEZONE)
    price_entity = str(options["price_entity"])
    margin = float(options["price_opportunity_margin_eur_per_kwh"])
    mode = HomeAssistantDispatchMode(str(options["mode"]))

    price_state = runtime._request_json(f"/api/states/{price_entity}", token)
    forecast = runtime._price_forecast(price_state, now=evaluated_at)
    pipeline = run_canonical_price_pipeline(
        forecast,
        evaluated_at=evaluated_at,
        price_margin_eur_per_kwh=margin,
    )

    price_opportunities = tuple(
        item for item in pipeline.opportunities.opportunities if item.kind in PRICE_KINDS
    )
    low_opportunities = tuple(
        item
        for item in price_opportunities
        if item.kind is OpportunityKind.LOWEST_PRICE_WINDOW
    )
    high_opportunities = tuple(
        item
        for item in price_opportunities
        if item.kind is OpportunityKind.HIGH_EXPORT_VALUE_WINDOW
    )

    event: dict[str, object] = {
        "event": "picot_price_decision",
        "evaluated_at": evaluated_at.isoformat(),
        "mode": mode.value,
        "strategy": "Price Driven v2 canonical pipeline",
        "strategy_id": "price-driven-v2-canonical",
        "strategy_version": pipeline.snapshot.strategy.strategy_version,
        "snapshot_id": pipeline.snapshot.snapshot_id,
        "planning_horizon_starts_at": pipeline.snapshot.captured_at.isoformat(),
        "planning_horizon_ends_at": pipeline.snapshot.horizon_end.isoformat(),
        "current_price_eur_per_kwh": _current_price(
            forecast,
            evaluated_at=evaluated_at,
        ),
        "price_opportunity_margin_eur_per_kwh": margin,
        "low_price_margin_eur_per_kwh": margin,
        "high_price_margin_eur_per_kwh": margin,
        "price_opportunity_count": len(price_opportunities),
        "low_price_opportunity_count": len(low_opportunities),
        "high_price_opportunity_count": len(high_opportunities),
        "price_opportunities": _serialize_opportunities(pipeline.opportunities),
        "candidate_count": len(pipeline.candidates.candidates),
        "candidate_exclusion_count": len(pipeline.candidates.exclusions),
        "candidate_exclusions": _serialize_candidate_exclusions(pipeline.candidates),
        "dispatch_status": "blocked_by_candidate_contract",
        "control_change_allowed": False,
        "pipeline_stage_reached": "candidate_generation",
        "reason": (
            "Canonical price opportunities reached Candidate Generation. Cost-first "
            "control remains excluded until the required ADR contract exists."
        ),
        "planner_interval_seconds": int(options["planner_interval_seconds"]),
    }
    event.update(
        _price_entry_observation(
            pipeline.opportunities,
            forecast,
            evaluated_at=evaluated_at,
        )
    )
    return event
