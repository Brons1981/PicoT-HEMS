"""Runtime adapter for Price Driven v2.

This module connects the price-only v2 strategy to the existing Home Assistant
runtime contract. It deliberately does not consume PV, battery SoC, household
load, EV demand or Solcast confidence yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from picot.addon import runtime
from picot.domain.forecast import ForecastSeries
from picot.domain.home_assistant import HomeAssistantDispatchMode
from picot.planner.price_driven_strategy_v2 import (
    PriceDrivenDecisionV2,
    PriceDrivenStrategyV2,
    PriceDrivenStrategyV2Config,
)

PRICE_ENTRY_DELAY_MINUTES = (15, 30, 45, 60)


def _serialize_opportunities(decision: PriceDrivenDecisionV2) -> list[dict[str, object]]:
    return [
        {
            "rank": opportunity.rank,
            "starts_at": opportunity.starts_at.isoformat(),
            "ends_at": opportunity.ends_at.isoformat(),
            "point_count": opportunity.point_count,
            "average_price_eur_per_kwh": opportunity.average_price_eur_per_kwh,
            "minimum_price_eur_per_kwh": opportunity.minimum_price_eur_per_kwh,
            "maximum_price_eur_per_kwh": opportunity.maximum_price_eur_per_kwh,
        }
        for opportunity in decision.opportunities
    ]


def _runtime_window(decision: PriceDrivenDecisionV2) -> tuple[str | None, str | None]:
    """Expose the active or next opportunity through the legacy scheduler contract."""

    active = next(
        (
            opportunity
            for opportunity in decision.opportunities
            if opportunity.rank == decision.active_opportunity_rank
        ),
        None,
    )
    if active is not None:
        return active.starts_at.isoformat(), active.ends_at.isoformat()

    next_opportunity = next(
        (
            opportunity
            for opportunity in decision.opportunities
            if opportunity.rank == decision.next_opportunity_rank
        ),
        None,
    )
    if next_opportunity is not None:
        return next_opportunity.starts_at.isoformat(), next_opportunity.ends_at.isoformat()
    return None, None


def _price_entry_observation(
    decision: PriceDrivenDecisionV2,
    forecast: ForecastSeries,
) -> dict[str, object]:
    """Compare threshold-entry price with later prices, without changing control.

    Price Driven v2 currently makes a qualifying opportunity actionable from its
    first point. This observation records whether later points inside that same
    opportunity were cheaper, so the next-day forensic review can distinguish
    opportunity detection from optimal action placement.
    """

    rank = decision.active_opportunity_rank or decision.next_opportunity_rank
    opportunity = next(
        (item for item in decision.opportunities if item.rank == rank),
        None,
    )
    if opportunity is None:
        return {
            "price_entry_observation_status": "no_opportunity",
            "price_entry_observation_only": True,
            "price_entry_replan_input": False,
            "price_entry_limitation": (
                "No active or next price opportunity is available for entry comparison."
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
            "price_entry_opportunity_rank": opportunity.rank,
            "price_entry_opportunity_starts_at": opportunity.starts_at.isoformat(),
            "price_entry_opportunity_ends_at": opportunity.ends_at.isoformat(),
            "price_entry_limitation": (
                "The opportunity exists, but matching forecast points were unavailable."
            ),
        }

    entry = points[0]
    later_points = points[1:]
    best_later = min(later_points, key=lambda point: (point.value, point.starts_at)) if later_points else None
    better_later = best_later is not None and best_later.value < entry.value

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
            "better_later_price_exists" if better_later else "entry_is_lowest_so_far"
        ),
        "price_entry_observation_only": True,
        "price_entry_replan_input": False,
        "price_entry_opportunity_rank": opportunity.rank,
        "price_entry_opportunity_starts_at": opportunity.starts_at.isoformat(),
        "price_entry_opportunity_ends_at": opportunity.ends_at.isoformat(),
        "price_entry_reference_starts_at": entry.starts_at.isoformat(),
        "price_entry_reference_price_eur_per_kwh": entry.value,
        "price_entry_better_later_price_exists": better_later,
        "price_entry_alternatives": alternatives,
        "price_entry_limitation": (
            "Price-only counterfactual: later prices are compared inside the same "
            "opportunity, but battery SoC, required energy, charge duration, PV, load, "
            "RTE and device constraints are not yet used to prove feasibility."
        ),
    }
    if best_later is not None:
        result.update(
            {
                "price_entry_best_later_starts_at": best_later.starts_at.isoformat(),
                "price_entry_best_later_price_eur_per_kwh": best_later.value,
                "price_entry_best_later_saving_eur_per_kwh": entry.value - best_later.value,
            }
        )
    return result


def run_planner_once(
    options: dict[str, Any],
    token: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run Price Driven v2 through the existing controlled dispatch contract."""

    evaluated_at = now or datetime.now(runtime.LOCAL_TIMEZONE)
    price_entity = str(options["price_entity"])
    target_entity = str(options["target_entity"])
    margin = float(options["price_opportunity_margin_eur_per_kwh"])
    mode = HomeAssistantDispatchMode(str(options["mode"]))

    price_state = runtime._request_json(f"/api/states/{price_entity}", token)
    target_state = runtime._request_json(f"/api/states/{target_entity}", token)
    forecast: ForecastSeries = runtime._price_forecast(price_state, now=evaluated_at)
    decision = PriceDrivenStrategyV2().evaluate(
        PriceDrivenStrategyV2Config(
            max_price_above_daily_min_eur_per_kwh=margin,
        ),
        forecast,
        evaluated_at=evaluated_at,
    )
    if decision.primitive is None:
        raise RuntimeError("Price Driven v2 returned no execution primitive.")

    desired_option = runtime._desired_option(decision.primitive)
    current_option = str(target_state.get("state", "unknown"))
    dispatch_status = "skipped_already_active"
    if current_option != desired_option:
        dispatch_status = runtime._dispatch(
            primitive=decision.primitive,
            desired_option=desired_option,
            target_entity=target_entity,
            mode=mode,
            token=token,
            now=evaluated_at,
        )

    window_starts_at, window_ends_at = _runtime_window(decision)
    event: dict[str, object] = {
        "event": "picot_price_decision",
        "evaluated_at": evaluated_at.isoformat(),
        "mode": mode.value,
        "strategy": "Price Driven v2",
        "strategy_id": decision.strategy_id,
        "strategy_version": decision.strategy_version,
        "current_option": current_option,
        "desired_option": desired_option,
        "reason": decision.reason,
        "window_starts_at": window_starts_at,
        "window_ends_at": window_ends_at,
        "current_price_eur_per_kwh": decision.current_price_eur_per_kwh,
        "daily_minimum_price_eur_per_kwh": decision.daily_minimum_price_eur_per_kwh,
        "price_threshold_eur_per_kwh": decision.price_threshold_eur_per_kwh,
        "price_opportunity_margin_eur_per_kwh": margin,
        "active_opportunity_rank": decision.active_opportunity_rank,
        "next_opportunity_rank": decision.next_opportunity_rank,
        "price_opportunity_count": len(decision.opportunities),
        "price_opportunities": _serialize_opportunities(decision),
        "dispatch_status": dispatch_status,
        "planner_interval_seconds": int(options["planner_interval_seconds"]),
    }
    event.update(_price_entry_observation(decision, forecast))
    return event
