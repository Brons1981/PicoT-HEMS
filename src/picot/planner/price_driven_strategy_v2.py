"""Price Driven v2 strategy based on multiple price opportunities.

This strategy deliberately remains price-only. It consumes all price opportunities
for the planning date and exposes them to later planner layers. PV, battery SoC,
household load, EV demand and forecast-confidence based replanning are not part of
this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastSeries
from picot.planner.price_opportunity import (
    PriceOpportunity,
    PriceOpportunityAnalyzer,
    PriceOpportunityConfig,
)

STRATEGY_ID = "price-driven-v2"
STRATEGY_VERSION = 2


@dataclass(frozen=True, slots=True)
class PriceDrivenStrategyV2Config:
    """Configuration for price-only opportunity based planning."""

    max_price_above_daily_min_eur_per_kwh: float
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class PriceDrivenDecisionV2:
    """Traceable outcome of one Price Driven v2 evaluation."""

    strategy_id: str
    strategy_version: int
    evaluated_at: datetime
    primitive: ExecutionPrimitive | None
    reason: str
    opportunities: tuple[PriceOpportunity, ...]
    active_opportunity_rank: int | None
    next_opportunity_rank: int | None
    current_price_eur_per_kwh: float | None
    daily_minimum_price_eur_per_kwh: float | None
    price_threshold_eur_per_kwh: float | None
    next_evaluation_at: datetime | None


class PriceDrivenStrategyV2:
    """Use all qualifying price opportunities instead of one fixed-size window."""

    def evaluate(
        self,
        config: PriceDrivenStrategyV2Config,
        price_forecast: ForecastSeries,
        *,
        evaluated_at: datetime,
    ) -> PriceDrivenDecisionV2:
        analysis = PriceOpportunityAnalyzer().analyze(
            PriceOpportunityConfig(
                max_price_above_daily_min_eur_per_kwh=(
                    config.max_price_above_daily_min_eur_per_kwh
                ),
                enabled=config.enabled,
            ),
            price_forecast,
            evaluated_at=evaluated_at,
        )

        current_price = next(
            (
                point.value
                for point in price_forecast.points
                if point.starts_at <= evaluated_at < point.ends_at
            ),
            None,
        )

        if not config.enabled:
            return PriceDrivenDecisionV2(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                evaluated_at=evaluated_at,
                primitive=None,
                reason="Price Driven v2 is disabled.",
                opportunities=(),
                active_opportunity_rank=None,
                next_opportunity_rank=None,
                current_price_eur_per_kwh=current_price,
                daily_minimum_price_eur_per_kwh=(
                    analysis.daily_minimum_price_eur_per_kwh
                ),
                price_threshold_eur_per_kwh=analysis.price_threshold_eur_per_kwh,
                next_evaluation_at=None,
            )

        opportunities = analysis.opportunities
        active = next(
            (
                opportunity
                for opportunity in opportunities
                if opportunity.starts_at <= evaluated_at < opportunity.ends_at
            ),
            None,
        )
        future = tuple(
            opportunity
            for opportunity in opportunities
            if opportunity.starts_at > evaluated_at
        )
        next_opportunity = min(future, key=lambda item: item.starts_at) if future else None

        if active is not None:
            primitive = ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            reason = (
                "A qualifying price opportunity is active; all remaining price "
                "opportunities stay available to later planner layers."
            )
            next_evaluation_at = active.ends_at
        else:
            primitive = ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
            if next_opportunity is not None:
                reason = (
                    "Waiting for the next qualifying price opportunity; later "
                    "opportunities remain available for replanning."
                )
                next_evaluation_at = next_opportunity.starts_at
            else:
                reason = "No qualifying price opportunities remain for the planning date."
                next_evaluation_at = None

        return PriceDrivenDecisionV2(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            evaluated_at=evaluated_at,
            primitive=primitive,
            reason=reason,
            opportunities=opportunities,
            active_opportunity_rank=active.rank if active is not None else None,
            next_opportunity_rank=(
                next_opportunity.rank if next_opportunity is not None else None
            ),
            current_price_eur_per_kwh=current_price,
            daily_minimum_price_eur_per_kwh=analysis.daily_minimum_price_eur_per_kwh,
            price_threshold_eur_per_kwh=analysis.price_threshold_eur_per_kwh,
            next_evaluation_at=next_evaluation_at,
        )
