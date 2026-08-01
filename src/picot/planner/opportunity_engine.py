"""Deterministic Opportunity Engine implementation.

The engine derives objective facts only. It never selects devices, assigns
power, scores candidates or creates execution plans. See ADR-023.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from picot.domain.forecast import ForecastKind, ForecastPoint, ForecastSeries
from picot.domain.opportunity import (
    EvidenceReference,
    Opportunity,
    OpportunityKind,
    OpportunityLifecycle,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot


@dataclass(frozen=True, slots=True)
class _NegativeWindow:
    starts_at: datetime
    ends_at: datetime
    point_indexes: tuple[int, ...]
    confidence: float


class OpportunityEngine:
    """Derive immutable opportunities from one Planning Input Snapshot."""

    def detect(self, snapshot: PlanningInputSnapshot) -> OpportunitySet:
        """Detect all currently implemented opportunity kinds."""

        opportunities: list[Opportunity] = []
        sequence = 1

        for series in snapshot.forecasts.by_kind(ForecastKind.ENERGY_PRICE):
            for window in self._negative_price_windows(series, snapshot):
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"{snapshot.snapshot_id}:negative-price:{sequence}",
                        snapshot_id=snapshot.snapshot_id,
                        kind=OpportunityKind.NEGATIVE_PRICE_WINDOW,
                        starts_at=window.starts_at,
                        ends_at=window.ends_at,
                        confidence=window.confidence,
                        lifecycle=OpportunityLifecycle.DETECTED,
                        evidence=(
                            EvidenceReference(
                                source_id=series.forecast_id,
                                point_indexes=window.point_indexes,
                            ),
                        ),
                    )
                )
                sequence += 1

        return OpportunitySet(
            snapshot_id=snapshot.snapshot_id,
            opportunities=tuple(opportunities),
        )

    def _negative_price_windows(
        self,
        series: ForecastSeries,
        snapshot: PlanningInputSnapshot,
    ) -> tuple[_NegativeWindow, ...]:
        windows: list[_NegativeWindow] = []
        current: list[tuple[int, ForecastPoint]] = []

        def flush() -> None:
            if not current:
                return
            first = current[0][1]
            last = current[-1][1]
            windows.append(
                _NegativeWindow(
                    starts_at=max(first.starts_at, snapshot.captured_at),
                    ends_at=min(last.ends_at, snapshot.horizon_end),
                    point_indexes=tuple(index for index, _ in current),
                    confidence=min(point.confidence for _, point in current),
                )
            )
            current.clear()

        for index, point in enumerate(series.points):
            overlaps_horizon = (
                point.ends_at > snapshot.captured_at
                and point.starts_at < snapshot.horizon_end
            )
            is_negative = point.value < 0.0
            contiguous = not current or current[-1][1].ends_at == point.starts_at

            if overlaps_horizon and is_negative and contiguous:
                current.append((index, point))
                continue

            flush()
            if overlaps_horizon and is_negative:
                current.append((index, point))

        flush()
        return tuple(windows)
