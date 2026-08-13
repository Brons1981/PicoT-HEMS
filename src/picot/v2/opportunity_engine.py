"""Canonical PicoT v2 Opportunity Engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from zoneinfo import ZoneInfo

from picot.v2.contracts import (
    Opportunity,
    OpportunityEvidenceRef,
    OpportunityMetrics,
    OpportunitySet,
    PlanningInputSnapshot,
    PriceForecastPoint,
)

NEGATIVE_PRICE_WINDOW = "NEGATIVE_PRICE_WINDOW"
LOWEST_PRICE_WINDOW = "LOWEST_PRICE_WINDOW"
HIGH_EXPORT_VALUE_WINDOW = "HIGH_EXPORT_VALUE_WINDOW"


@dataclass(frozen=True, slots=True)
class PriceOpportunityConfig:
    low_price_margin_eur_per_kwh: float
    high_price_margin_eur_per_kwh: float
    config_version: str
    market_timezone: str = "Europe/Amsterdam"

    def __post_init__(self) -> None:
        for name, value in (
            ("low_price_margin_eur_per_kwh", self.low_price_margin_eur_per_kwh),
            ("high_price_margin_eur_per_kwh", self.high_price_margin_eur_per_kwh),
        ):
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not self.config_version.strip():
            raise ValueError("config_version must be explicit")
        ZoneInfo(self.market_timezone)


def _stable_id(prefix: str, seed: str) -> str:
    return f"{prefix}-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _validate_point(point: PriceForecastPoint) -> None:
    if not _aware(point.starts_at) or not _aware(point.ends_at):
        raise ValueError("price point timestamps must be timezone-aware")
    if point.ends_at <= point.starts_at:
        raise ValueError("price point interval must have positive duration")
    if not isfinite(point.value_eur_per_kwh):
        raise ValueError("price point value must be finite")
    if not isfinite(point.confidence) or not 0.0 <= point.confidence <= 1.0:
        raise ValueError("price point confidence must be between 0 and 1")
    if not point.point_id or not point.evidence_id:
        raise ValueError("price point identity and evidence must be explicit")


def _contiguous(left: PriceForecastPoint, right: PriceForecastPoint) -> bool:
    return left.ends_at == right.starts_at


def _weighted_average(points: tuple[PriceForecastPoint, ...]) -> float:
    duration = sum((p.ends_at - p.starts_at).total_seconds() for p in points)
    return sum(
        p.value_eur_per_kwh * (p.ends_at - p.starts_at).total_seconds() for p in points
    ) / duration


def _group_strict(
    points: tuple[PriceForecastPoint, ...], qualifies: tuple[bool, ...]
) -> tuple[tuple[PriceForecastPoint, ...], ...]:
    groups: list[tuple[PriceForecastPoint, ...]] = []
    current: list[PriceForecastPoint] = []
    for index, point in enumerate(points):
        if not qualifies[index]:
            if current:
                groups.append(tuple(current))
                current = []
            continue
        if current and not _contiguous(current[-1], point):
            groups.append(tuple(current))
            current = []
        current.append(point)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _group_relative(
    points: tuple[PriceForecastPoint, ...],
    qualifies: tuple[bool, ...],
    *,
    boundary: float,
    low: bool,
) -> tuple[tuple[tuple[PriceForecastPoint, ...], int], ...]:
    groups: list[tuple[tuple[PriceForecastPoint, ...], int]] = []
    index = 0
    while index < len(points):
        if not qualifies[index]:
            index += 1
            continue
        current = [points[index]]
        bridged = 0
        index += 1
        while index < len(points):
            point = points[index]
            if not _contiguous(current[-1], point):
                break
            if qualifies[index]:
                current.append(point)
                index += 1
                continue
            next_index = index + 1
            if next_index >= len(points) or not qualifies[next_index]:
                break
            following = points[next_index]
            if not _contiguous(point, following):
                break
            tentative = tuple((*current, point, following))
            average = _weighted_average(tentative)
            aggregate_ok = average <= boundary if low else average >= boundary
            if not aggregate_ok:
                break
            current.extend((point, following))
            bridged += 1
            index += 2
        groups.append((tuple(current), bridged))
    return tuple(groups)


def _evidence_refs(points: tuple[PriceForecastPoint, ...]) -> tuple[OpportunityEvidenceRef, ...]:
    by_evidence: dict[str, list[str]] = {}
    for point in points:
        by_evidence.setdefault(point.evidence_id, []).append(point.point_id)
    return tuple(
        OpportunityEvidenceRef(evidence_id=evidence_id, point_ids=tuple(point_ids))
        for evidence_id, point_ids in sorted(by_evidence.items())
    )


def _opportunity(
    snapshot: PlanningInputSnapshot,
    *,
    kind: str,
    points: tuple[PriceForecastPoint, ...],
    boundary: float | None,
    bridged_interval_count: int,
) -> Opportunity:
    starts_at = points[0].starts_at
    ends_at = points[-1].ends_at
    point_seed = "|".join(point.point_id for point in points)
    opportunity_id = _stable_id(
        "opportunity",
        f"{snapshot.snapshot_id}|{kind}|{starts_at.isoformat()}|{ends_at.isoformat()}|"
        f"{boundary}|{point_seed}",
    )
    return Opportunity(
        opportunity_id=opportunity_id,
        run_id=snapshot.run_id,
        snapshot_id=snapshot.snapshot_id,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        confidence=min(point.confidence for point in points),
        lifecycle_status="DETECTED",
        evidence=_evidence_refs(points),
        metrics=OpportunityMetrics(
            duration_seconds=(ends_at - starts_at).total_seconds(),
            average_price_eur_per_kwh=_weighted_average(points),
            minimum_price_eur_per_kwh=min(point.value_eur_per_kwh for point in points),
            maximum_price_eur_per_kwh=max(point.value_eur_per_kwh for point in points),
            boundary_eur_per_kwh=boundary,
            source_interval_count=len(points),
            bridged_interval_count=bridged_interval_count,
        ),
    )


class OpportunityEngine:
    def detect(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        price_config: PriceOpportunityConfig | None,
    ) -> OpportunitySet:
        set_id = _stable_id("opportunity-set", snapshot.snapshot_id)
        if snapshot.horizon_end is None:
            return OpportunitySet(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                opportunity_set_id=set_id,
                detection_status="blocked",
                detection_reason="planning_horizon_missing",
            )
        if not _aware(snapshot.captured_at) or not _aware(snapshot.horizon_end):
            raise ValueError("planning horizon timestamps must be timezone-aware")
        if snapshot.horizon_end <= snapshot.captured_at:
            raise ValueError("planning horizon must end after captured_at")
        if not snapshot.price_points:
            return OpportunitySet(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                opportunity_set_id=set_id,
                detection_status="blocked",
                detection_reason="price_points_missing",
            )
        if price_config is None:
            return OpportunitySet(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                opportunity_set_id=set_id,
                detection_status="blocked",
                detection_reason="price_detector_config_missing",
            )

        points = tuple(sorted(snapshot.price_points, key=lambda point: (point.starts_at, point.ends_at)))
        for point in points:
            _validate_point(point)
        filtered = tuple(
            point
            for point in points
            if point.ends_at > snapshot.captured_at and point.starts_at < snapshot.horizon_end
        )
        if not filtered:
            return OpportunitySet(
                run_id=snapshot.run_id,
                snapshot_id=snapshot.snapshot_id,
                opportunity_set_id=set_id,
                detection_status="ready",
                detection_reason="no_price_points_in_horizon",
                detector_config_version=price_config.config_version,
            )

        timezone = ZoneInfo(price_config.market_timezone)
        by_date: dict[date, list[PriceForecastPoint]] = {}
        for point in filtered:
            by_date.setdefault(point.starts_at.astimezone(timezone).date(), []).append(point)

        opportunities: list[Opportunity] = []
        for local_date in sorted(by_date):
            day_points = tuple(by_date[local_date])
            values = tuple(point.value_eur_per_kwh for point in day_points)
            low_boundary = min(values) + price_config.low_price_margin_eur_per_kwh
            high_boundary = max(values) - price_config.high_price_margin_eur_per_kwh

            for group in _group_strict(
                day_points,
                tuple(point.value_eur_per_kwh < 0.0 for point in day_points),
            ):
                opportunities.append(
                    _opportunity(
                        snapshot,
                        kind=NEGATIVE_PRICE_WINDOW,
                        points=group,
                        boundary=0.0,
                        bridged_interval_count=0,
                    )
                )

            low = tuple(point.value_eur_per_kwh <= low_boundary for point in day_points)
            for group, bridged in _group_relative(
                day_points, low, boundary=low_boundary, low=True
            ):
                opportunities.append(
                    _opportunity(
                        snapshot,
                        kind=LOWEST_PRICE_WINDOW,
                        points=group,
                        boundary=low_boundary,
                        bridged_interval_count=bridged,
                    )
                )

            high = tuple(point.value_eur_per_kwh >= high_boundary for point in day_points)
            for group, bridged in _group_relative(
                day_points, high, boundary=high_boundary, low=False
            ):
                opportunities.append(
                    _opportunity(
                        snapshot,
                        kind=HIGH_EXPORT_VALUE_WINDOW,
                        points=group,
                        boundary=high_boundary,
                        bridged_interval_count=bridged,
                    )
                )

        ordered = tuple(
            sorted(
                opportunities,
                key=lambda item: (item.starts_at, item.ends_at, item.kind, item.opportunity_id),
            )
        )
        return OpportunitySet(
            run_id=snapshot.run_id,
            snapshot_id=snapshot.snapshot_id,
            opportunity_set_id=set_id,
            opportunity_ids=tuple(item.opportunity_id for item in ordered),
            opportunities=ordered,
            detection_status="ready",
            detector_config_version=price_config.config_version,
        )
