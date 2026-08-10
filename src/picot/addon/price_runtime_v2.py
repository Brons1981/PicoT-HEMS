"""Runtime adapter for Price Driven v2.

This module connects the price-only v2 strategy to the existing Home Assistant
runtime contract. It deliberately does not consume PV, battery SoC, household
load, EV demand or Solcast confidence yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from picot.addon import runtime
from picot.domain.forecast import ForecastSeries
from picot.domain.home_assistant import HomeAssistantDispatchMode
from picot.planner.price_driven_strategy_v2 import (
    PriceDrivenDecisionV2,
    PriceDrivenStrategyV2,
    PriceDrivenStrategyV2Config,
)


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
    return {
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
