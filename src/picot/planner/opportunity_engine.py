"""Deterministic Opportunity Engine implementation.

The engine derives objective facts only. It never selects devices, assigns
power, scores candidates or creates execution plans. See ADR-023 and ADR-036.
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
    OpportunityMetric,
    OpportunityMetricKind,
    OpportunitySet,
)
from picot.domain.planning_input_snapshot import PlanningInputSnapshot
from picot.planner.price_opportunity_detection import (
    DetectedPriceWindow,
    PriceOpportunityDetectionConfig,
    PriceOpportunityDetector,
)


@dataclass(frozen=True, slots=True)
class _NegativeWindow:
    starts_at: datetime
    ends_at: datetime
    point_indexes: tuple[int, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class _PvSurplusWindow:
    starts_at: datetime
    ends_at: datetime
    pv_point_indexes: tuple[int, ...]
    load_point_indexes: tuple[int, ...]
    confidence: float
    minimum_expected_power_w: float


class OpportunityEngine:
    """Derive immutable opportunities from one Planning Input Snapshot."""

    def detect(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        price_config: PriceOpportunityDetectionConfig | None = None,
    ) -> OpportunitySet:
        """Detect all supported opportunities using only explicit configuration."""

        opportunities: list[Opportunity] = []
        sequence = 1

        for series in snapshot.forecasts.by_kind(ForecastKind.ENERGY_PRICE):
            for negative_window in self._negative_price_windows(series, snapshot):
                opportunities.append(
                    Opportunity(
                        opportunity_id=f"{snapshot.snapshot_id}:negative-price:{sequence}",
                        snapshot_id=snapshot.snapshot_id,
                        kind=OpportunityKind.NEGATIVE_PRICE_WINDOW,
                        starts_at=negative_window.starts_at,
                        ends_at=negative_window.ends_at,
                        confidence=negative_window.confidence,
                        lifecycle=OpportunityLifecycle.DETECTED,
                        evidence=(
                            EvidenceReference(
                                source_id=series.forecast_id,
                                point_indexes=negative_window.point_indexes,
                            ),
                        ),
                    )
                )
                sequence += 1

            if price_config is None:
                continue

            detected = PriceOpportunityDetector().detect(series, snapshot, price_config)
            for price_window in detected:
                opportunities.append(
                    self._price_opportunity(
                        snapshot=snapshot,
                        series=series,
                        window=price_window,
                        config=price_config,
                        sequence=sequence,
                    )
                )
                sequence += 1

        pv_series = snapshot.forecasts.by_kind(ForecastKind.PV_POWER)
        load_series = snapshot.forecasts.by_kind(ForecastKind.HOUSEHOLD_LOAD)
        for pv in pv_series:
            for load in load_series:
                for surplus_window in self._pv_surplus_windows(pv, load, snapshot):
                    opportunities.append(
                        Opportunity(
                            opportunity_id=f"{snapshot.snapshot_id}:pv-surplus:{sequence}",
                            snapshot_id=snapshot.snapshot_id,
                            kind=OpportunityKind.PV_SURPLUS_WINDOW,
                            starts_at=surplus_window.starts_at,
                            ends_at=surplus_window.ends_at,
                            confidence=surplus_window.confidence,
                            lifecycle=OpportunityLifecycle.DETECTED,
                            evidence=(
                                EvidenceReference(
                                    source_id=pv.forecast_id,
                                    point_indexes=surplus_window.pv_point_indexes,
                                ),
                                EvidenceReference(
                                    source_id=load.forecast_id,
                                    point_indexes=surplus_window.load_point_indexes,
                                ),
                            ),
                            metrics=(
                                OpportunityMetric(
                                    kind=OpportunityMetricKind.MINIMUM_EXPECTED_POWER_W,
                                    value=surplus_window.minimum_expected_power_w,
                                ),
                            ),
                        )
                    )
                    sequence += 1

        return OpportunitySet(
            snapshot_id=snapshot.snapshot_id,
            opportunities=tuple(opportunities),
        )

    @staticmethod
    def _price_opportunity(
        *,
        snapshot: PlanningInputSnapshot,
        series: ForecastSeries,
        window: DetectedPriceWindow,
        config: PriceOpportunityDetectionConfig,
        sequence: int,
    ) -> Opportunity:
        prefix = (
            "lowest-price"
            if window.kind is OpportunityKind.LOWEST_PRICE_WINDOW
            else "high-export-value"
        )
        metrics = (
            OpportunityMetric(
                kind=OpportunityMetricKind.AVERAGE_ENERGY_PRICE_EUR_PER_KWH,
                value=window.average_price_eur_per_kwh,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.MINIMUM_ENERGY_PRICE_EUR_PER_KWH,
                value=window.minimum_price_eur_per_kwh,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.MAXIMUM_ENERGY_PRICE_EUR_PER_KWH,
                value=window.maximum_price_eur_per_kwh,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.PRICE_REFERENCE_EUR_PER_KWH,
                value=window.reference_price_eur_per_kwh,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.PRICE_BOUNDARY_EUR_PER_KWH,
                value=window.boundary_price_eur_per_kwh,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.DURATION_SECONDS,
                value=window.duration_seconds,
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.SOURCE_INTERVAL_COUNT,
                value=float(window.source_interval_count),
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.BRIDGED_INTERVAL_COUNT,
                value=float(window.bridged_interval_count),
            ),
            OpportunityMetric(
                kind=OpportunityMetricKind.PRICE_DETECTION_CONFIG_VERSION,
                value=float(config.config_version),
            ),
        )
        return Opportunity(
            opportunity_id=f"{snapshot.snapshot_id}:{prefix}:{sequence}",
            snapshot_id=snapshot.snapshot_id,
            kind=window.kind,
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
            metrics=metrics,
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

    def _pv_surplus_windows(
        self,
        pv_series: ForecastSeries,
        load_series: ForecastSeries,
        snapshot: PlanningInputSnapshot,
    ) -> tuple[_PvSurplusWindow, ...]:
        if pv_series.unit != "W" or load_series.unit != "W":
            return ()

        load_points = {
            (point.starts_at, point.ends_at): (index, point)
            for index, point in enumerate(load_series.points)
        }
        windows: list[_PvSurplusWindow] = []
        current: list[tuple[int, ForecastPoint, int, ForecastPoint, float]] = []

        def flush() -> None:
            if not current:
                return
            first_pv = current[0][1]
            last_pv = current[-1][1]
            windows.append(
                _PvSurplusWindow(
                    starts_at=max(first_pv.starts_at, snapshot.captured_at),
                    ends_at=min(last_pv.ends_at, snapshot.horizon_end),
                    pv_point_indexes=tuple(item[0] for item in current),
                    load_point_indexes=tuple(item[2] for item in current),
                    confidence=min(
                        min(item[1].confidence, item[3].confidence) for item in current
                    ),
                    minimum_expected_power_w=min(item[4] for item in current),
                )
            )
            current.clear()

        for pv_index, pv_point in enumerate(pv_series.points):
            load_match = load_points.get((pv_point.starts_at, pv_point.ends_at))
            if load_match is None:
                flush()
                continue

            load_index, load_point = load_match
            overlaps_horizon = (
                pv_point.ends_at > snapshot.captured_at
                and pv_point.starts_at < snapshot.horizon_end
            )
            surplus_w = pv_point.value - load_point.value
            contiguous = not current or current[-1][1].ends_at == pv_point.starts_at

            if overlaps_horizon and surplus_w > 0.0 and contiguous:
                current.append((pv_index, pv_point, load_index, load_point, surplus_w))
                continue

            flush()
            if overlaps_horizon and surplus_w > 0.0:
                current.append((pv_index, pv_point, load_index, load_point, surplus_w))

        flush()
        return tuple(windows)
