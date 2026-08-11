"""Deterministic relative price-window detection for the Opportunity Engine.

This module is an implementation detail of the canonical Opportunity Engine.
It does not define a second planning model and never selects actions or devices.
See ADR-036.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

from picot.domain.forecast import ForecastPoint, ForecastSeries
from picot.domain.opportunity import OpportunityKind
from picot.domain.planning_input_snapshot import PlanningInputSnapshot


@dataclass(frozen=True, slots=True)
class PriceOpportunityDetectionConfig:
    """Explicit versioned configuration for ADR-036 relative price detection."""

    config_version: int
    low_price_margin_eur_per_kwh: float
    high_price_margin_eur_per_kwh: float

    def __post_init__(self) -> None:
        if self.config_version < 1:
            raise ValueError("Price detection config version must be at least 1.")
        for name, value in (
            ("low price margin", self.low_price_margin_eur_per_kwh),
            ("high price margin", self.high_price_margin_eur_per_kwh),
        ):
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"Price detection {name} must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class DetectedPriceWindow:
    """Internal deterministic result converted to a canonical Opportunity."""

    kind: OpportunityKind
    starts_at: datetime
    ends_at: datetime
    point_indexes: tuple[int, ...]
    confidence: float
    average_price_eur_per_kwh: float
    minimum_price_eur_per_kwh: float
    maximum_price_eur_per_kwh: float
    reference_price_eur_per_kwh: float
    boundary_price_eur_per_kwh: float
    bridged_interval_count: int

    @property
    def source_interval_count(self) -> int:
        return len(self.point_indexes)

    @property
    def duration_seconds(self) -> float:
        return (self.ends_at - self.starts_at).total_seconds()


class PriceOpportunityDetector:
    """Detect ADR-036 low-price and high-price windows over a rolling horizon."""

    def detect(
        self,
        series: ForecastSeries,
        snapshot: PlanningInputSnapshot,
        config: PriceOpportunityDetectionConfig,
    ) -> tuple[DetectedPriceWindow, ...]:
        if series.unit != "EUR/kWh":
            return ()

        horizon_points = tuple(
            (index, point)
            for index, point in enumerate(series.points)
            if point.ends_at > snapshot.captured_at
            and point.starts_at < snapshot.horizon_end
        )
        if not horizon_points:
            return ()

        market_timezone = series.points[0].starts_at.tzinfo
        represented_dates = sorted(
            {
                point.starts_at.astimezone(market_timezone).date()
                for _, point in horizon_points
            }
        )

        windows: list[DetectedPriceWindow] = []
        for market_date in represented_dates:
            all_day_points = tuple(
                (index, point)
                for index, point in enumerate(series.points)
                if point.starts_at.astimezone(market_timezone).date() == market_date
            )
            eligible_day_points = tuple(
                (index, point)
                for index, point in horizon_points
                if point.starts_at.astimezone(market_timezone).date() == market_date
            )
            if not all_day_points or not eligible_day_points:
                continue

            daily_minimum = min(point.value for _, point in all_day_points)
            low_boundary = daily_minimum + config.low_price_margin_eur_per_kwh
            windows.extend(
                self._build_windows(
                    kind=OpportunityKind.LOWEST_PRICE_WINDOW,
                    points=eligible_day_points,
                    market_date=market_date,
                    market_timezone=market_timezone,
                    reference_price=daily_minimum,
                    boundary_price=low_boundary,
                    snapshot=snapshot,
                )
            )

            daily_maximum = max(point.value for _, point in all_day_points)
            high_boundary = daily_maximum - config.high_price_margin_eur_per_kwh
            windows.extend(
                self._build_windows(
                    kind=OpportunityKind.HIGH_EXPORT_VALUE_WINDOW,
                    points=eligible_day_points,
                    market_date=market_date,
                    market_timezone=market_timezone,
                    reference_price=daily_maximum,
                    boundary_price=high_boundary,
                    snapshot=snapshot,
                )
            )

        return tuple(
            sorted(
                windows,
                key=lambda item: (item.starts_at, item.kind.value, item.point_indexes),
            )
        )

    def _build_windows(
        self,
        *,
        kind: OpportunityKind,
        points: tuple[tuple[int, ForecastPoint], ...],
        market_date: date,
        market_timezone: object,
        reference_price: float,
        boundary_price: float,
        snapshot: PlanningInputSnapshot,
    ) -> tuple[DetectedPriceWindow, ...]:
        windows: list[DetectedPriceWindow] = []
        current: list[tuple[int, ForecastPoint]] = []
        index = 0

        def qualifies(point: ForecastPoint) -> bool:
            if kind is OpportunityKind.LOWEST_PRICE_WINDOW:
                return point.value <= boundary_price
            return point.value >= boundary_price

        def aggregate_qualifies(items: list[tuple[int, ForecastPoint]]) -> bool:
            average = sum(point.value for _, point in items) / len(items)
            if kind is OpportunityKind.LOWEST_PRICE_WINDOW:
                return average <= boundary_price
            return average >= boundary_price

        def flush() -> None:
            if not current:
                return
            first = current[0][1]
            last = current[-1][1]
            starts_at = max(first.starts_at, snapshot.captured_at)
            ends_at = min(last.ends_at, snapshot.horizon_end)
            prices = tuple(point.value for _, point in current)
            windows.append(
                DetectedPriceWindow(
                    kind=kind,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    point_indexes=tuple(item_index for item_index, _ in current),
                    confidence=min(point.confidence for _, point in current),
                    average_price_eur_per_kwh=sum(prices) / len(prices),
                    minimum_price_eur_per_kwh=min(prices),
                    maximum_price_eur_per_kwh=max(prices),
                    reference_price_eur_per_kwh=reference_price,
                    boundary_price_eur_per_kwh=boundary_price,
                    bridged_interval_count=sum(
                        1 for _, point in current if not qualifies(point)
                    ),
                )
            )
            current.clear()

        while index < len(points):
            point_index, point = points[index]
            point_date = point.starts_at.astimezone(market_timezone).date()
            if point_date != market_date:
                flush()
                index += 1
                continue

            if qualifies(point):
                contiguous = not current or current[-1][1].ends_at == point.starts_at
                if not contiguous:
                    flush()
                current.append((point_index, point))
                index += 1
                continue

            next_item = points[index + 1] if index + 1 < len(points) else None
            can_bridge = False
            if current and next_item is not None:
                _, next_point = next_item
                next_date = next_point.starts_at.astimezone(market_timezone).date()
                can_bridge = (
                    current[-1][1].ends_at == point.starts_at
                    and point.ends_at == next_point.starts_at
                    and next_date == market_date
                    and qualifies(next_point)
                )
                if can_bridge:
                    merged = [*current, (point_index, point), next_item]
                    can_bridge = aggregate_qualifies(merged)

            if can_bridge and next_item is not None:
                current.extend(((point_index, point), next_item))
                index += 2
                continue

            flush()
            index += 1

        flush()
        return tuple(windows)
