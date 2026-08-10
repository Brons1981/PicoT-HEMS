"""Deterministic price-opportunity analysis for Price Driven v2.

This module deliberately analyses prices only. It does not consider PV,
battery SoC, household load, EV demand or dispatch state. Those concerns
belong to later planner layers that consume the resulting opportunities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries


@dataclass(frozen=True, slots=True)
class PriceOpportunityConfig:
    """Configuration for price-only opportunity detection."""

    max_price_above_daily_min_eur_per_kwh: float
    enabled: bool = True

    def __post_init__(self) -> None:
        margin = self.max_price_above_daily_min_eur_per_kwh
        if not isfinite(margin) or margin < 0.0:
            raise ValueError("Price-opportunity margin must be a finite non-negative value.")


@dataclass(frozen=True, slots=True)
class PriceOpportunity:
    """One contiguous period whose prices satisfy the opportunity threshold."""

    rank: int
    starts_at: datetime
    ends_at: datetime
    point_count: int
    average_price_eur_per_kwh: float
    minimum_price_eur_per_kwh: float
    maximum_price_eur_per_kwh: float


@dataclass(frozen=True, slots=True)
class PriceOpportunitySet:
    """Traceable price-only analysis result for one planning date."""

    evaluated_at: datetime
    daily_minimum_price_eur_per_kwh: float
    price_threshold_eur_per_kwh: float
    opportunities: tuple[PriceOpportunity, ...]


class PriceOpportunityAnalyzer:
    """Find and rank all contiguous price opportunities for the current day."""

    def analyze(
        self,
        config: PriceOpportunityConfig,
        price_forecast: ForecastSeries,
        *,
        evaluated_at: datetime,
    ) -> PriceOpportunitySet:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("Price-opportunity evaluation time must be timezone-aware.")
        if price_forecast.kind is not ForecastKind.ENERGY_PRICE:
            raise ValueError("Price Opportunity Analyzer requires an energy-price forecast.")
        if price_forecast.unit != "EUR/kWh":
            raise ValueError("Price Opportunity Analyzer requires prices in EUR/kWh.")
        if price_forecast.is_expired_at(evaluated_at):
            raise ValueError("Price forecast is expired.")

        forecast_timezone = price_forecast.points[0].starts_at.tzinfo
        planning_date = evaluated_at.astimezone(forecast_timezone).date()
        eligible = tuple(
            point
            for point in price_forecast.points
            if point.starts_at.astimezone(forecast_timezone).date() == planning_date
        )
        if not eligible:
            raise ValueError("Price forecast contains no points for the planning date.")

        daily_minimum = min(point.value for point in eligible)
        threshold = daily_minimum + config.max_price_above_daily_min_eur_per_kwh

        if not config.enabled:
            return PriceOpportunitySet(
                evaluated_at=evaluated_at,
                daily_minimum_price_eur_per_kwh=daily_minimum,
                price_threshold_eur_per_kwh=threshold,
                opportunities=(),
            )

        candidate_groups: list[list[ForecastPoint]] = []
        current_group: list[ForecastPoint] = []
        for point in eligible:
            qualifies = point.value <= threshold
            contiguous = not current_group or current_group[-1].ends_at == point.starts_at
            if qualifies and contiguous:
                current_group.append(point)
                continue
            if current_group:
                candidate_groups.append(current_group)
                current_group = []
            if qualifies:
                current_group = [point]
        if current_group:
            candidate_groups.append(current_group)

        unranked = [
            (
                group[0].starts_at,
                group[-1].ends_at,
                len(group),
                sum(point.value for point in group) / len(group),
                min(point.value for point in group),
                max(point.value for point in group),
            )
            for group in candidate_groups
        ]
        unranked.sort(key=lambda item: (item[3], item[4], item[0]))

        opportunities = tuple(
            PriceOpportunity(
                rank=index,
                starts_at=starts_at,
                ends_at=ends_at,
                point_count=point_count,
                average_price_eur_per_kwh=average_price,
                minimum_price_eur_per_kwh=minimum_price,
                maximum_price_eur_per_kwh=maximum_price,
            )
            for index, (
                starts_at,
                ends_at,
                point_count,
                average_price,
                minimum_price,
                maximum_price,
            ) in enumerate(unranked, start=1)
        )

        return PriceOpportunitySet(
            evaluated_at=evaluated_at,
            daily_minimum_price_eur_per_kwh=daily_minimum,
            price_threshold_eur_per_kwh=threshold,
            opportunities=opportunities,
        )
