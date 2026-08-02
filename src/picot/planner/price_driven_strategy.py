"""Deterministic price-driven strategy for the first live price validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.forecast import ForecastKind, ForecastSeries

STRATEGY_ID = "price-driven-v1"
STRATEGY_VERSION = 1


@dataclass(frozen=True, slots=True)
class PriceDrivenStrategyConfig:
    """Configuration for one contiguous cheapest-price window."""

    window_points: int
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.window_points < 1:
            raise ValueError("Price window must contain at least one forecast point.")


@dataclass(frozen=True, slots=True)
class PriceDrivenDecision:
    """Traceable outcome of one price-driven evaluation."""

    strategy_id: str
    strategy_version: int
    evaluated_at: datetime
    primitive: ExecutionPrimitive | None
    reason: str
    window_starts_at: datetime | None
    window_ends_at: datetime | None
    average_price_eur_per_kwh: float | None
    current_price_eur_per_kwh: float | None
    next_evaluation_at: datetime | None


class PriceDrivenStrategy:
    """Select the cheapest contiguous forecast window and desired battery mode."""

    def evaluate(
        self,
        config: PriceDrivenStrategyConfig,
        price_forecast: ForecastSeries,
        *,
        evaluated_at: datetime,
    ) -> PriceDrivenDecision:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("Strategy evaluation time must be timezone-aware.")
        if price_forecast.kind is not ForecastKind.ENERGY_PRICE:
            raise ValueError("Price Driven Strategy requires an energy-price forecast.")
        if price_forecast.unit != "EUR/kWh":
            raise ValueError("Price Driven Strategy requires prices in EUR/kWh.")
        if price_forecast.is_expired_at(evaluated_at):
            raise ValueError("Price forecast is expired.")
        if not config.enabled:
            return PriceDrivenDecision(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                evaluated_at=evaluated_at,
                primitive=None,
                reason="Price Driven Strategy is disabled.",
                window_starts_at=None,
                window_ends_at=None,
                average_price_eur_per_kwh=None,
                current_price_eur_per_kwh=None,
                next_evaluation_at=None,
            )

        forecast_timezone = price_forecast.points[0].starts_at.tzinfo
        planning_date = evaluated_at.astimezone(forecast_timezone).date()
        eligible = tuple(
            point
            for point in price_forecast.points
            if point.starts_at.astimezone(forecast_timezone).date() == planning_date
        )
        if len(eligible) < config.window_points:
            raise ValueError("Price forecast does not contain enough points for today.")

        windows = tuple(
            eligible[index : index + config.window_points]
            for index in range(len(eligible) - config.window_points + 1)
            if all(
                left.ends_at == right.starts_at
                for left, right in zip(
                    eligible[index : index + config.window_points],
                    eligible[index + 1 : index + config.window_points],
                    strict=False,
                )
            )
        )
        if not windows:
            raise ValueError("Price forecast has no contiguous candidate window for today.")

        selected = min(
            windows,
            key=lambda window: (
                sum(point.value for point in window) / len(window),
                window[0].starts_at,
            ),
        )
        starts_at = selected[0].starts_at
        ends_at = selected[-1].ends_at
        average_price = sum(point.value for point in selected) / len(selected)
        current = next(
            (
                point.value
                for point in price_forecast.points
                if point.starts_at <= evaluated_at < point.ends_at
            ),
            None,
        )

        inside_window = starts_at <= evaluated_at < ends_at
        primitive = (
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL
            if inside_window
            else ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
        )
        if evaluated_at < starts_at:
            reason = "Waiting for the selected cheapest contiguous price window."
            next_evaluation = starts_at
        elif inside_window:
            reason = "The selected cheapest contiguous price window is active."
            next_evaluation = ends_at
        else:
            reason = "The selected cheapest contiguous price window has ended."
            next_evaluation = None

        return PriceDrivenDecision(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            evaluated_at=evaluated_at,
            primitive=primitive,
            reason=reason,
            window_starts_at=starts_at,
            window_ends_at=ends_at,
            average_price_eur_per_kwh=average_price,
            current_price_eur_per_kwh=current,
            next_evaluation_at=next_evaluation,
        )
