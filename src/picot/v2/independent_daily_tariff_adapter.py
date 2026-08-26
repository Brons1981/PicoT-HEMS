"""Build explicit daily import/export tariffs from canonical price evidence."""

from __future__ import annotations

from datetime import datetime

from picot.domain.daily_reference_tariff import (
    DailyReferenceTariffInterval,
    DailyReferenceTariffSchedule,
)
from picot.v2.contracts import PlanningInputSnapshot, PriceForecastPoint

METHOD_VERSION = "v2-daily-tariff-policy-nl-2027:v2"
VAT_FACTOR = 1.21
ENERGY_TAX_EX_VAT_EUR_PER_KWH = 0.09161
SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH = 0.01653
EXPORT_ADDITION_EUR_PER_KWH = 0.02
EXPORT_TAX_TRANSITION = datetime.fromisoformat("2027-01-01T00:00:00+01:00")


class DailyReferenceTariffInputError(ValueError):
    """Canonical price evidence cannot prove a complete tariff schedule."""


class IndependentDailyTariffAdapter:
    """Apply the explicit Dutch 2026/2027 tariff policy observer-only."""

    def published_horizon_end(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        maximum_horizon_end: datetime,
    ) -> datetime:
        """Return the contiguous published tariff boundary, capped by policy."""
        if not snapshot.price_points:
            raise DailyReferenceTariffInputError("daily_tariff_prices_missing")
        cursor = snapshot.captured_at
        for point in sorted(snapshot.price_points, key=lambda item: item.starts_at):
            if point.ends_at <= cursor:
                continue
            if point.starts_at > cursor:
                break
            cursor = min(max(cursor, point.ends_at), maximum_horizon_end)
            if cursor == maximum_horizon_end:
                return cursor
        if cursor == snapshot.captured_at:
            raise DailyReferenceTariffInputError(
                "daily_tariff_price_coverage_incomplete"
            )
        return cursor

    def build(
        self,
        snapshot: PlanningInputSnapshot,
        *,
        horizon_end: datetime | None = None,
    ) -> DailyReferenceTariffSchedule:
        selected_horizon_end = horizon_end or snapshot.horizon_end
        if (
            selected_horizon_end is None
            or selected_horizon_end <= snapshot.captured_at
            or (
                snapshot.horizon_end is not None
                and selected_horizon_end > snapshot.horizon_end
            )
        ):
            raise DailyReferenceTariffInputError("daily_tariff_horizon_missing")
        if not snapshot.price_points:
            raise DailyReferenceTariffInputError("daily_tariff_prices_missing")
        points = tuple(sorted(snapshot.price_points, key=lambda item: item.starts_at))
        self._validate_coverage(
            points,
            starts_at=snapshot.captured_at,
            ends_at=selected_horizon_end,
        )
        boundaries = {snapshot.captured_at, selected_horizon_end}
        boundaries.update(
            point.starts_at
            for point in points
            if snapshot.captured_at < point.starts_at < selected_horizon_end
        )
        boundaries.update(
            point.ends_at
            for point in points
            if snapshot.captured_at < point.ends_at < selected_horizon_end
        )
        if snapshot.household_load_forecast is not None:
            boundaries.update(
                interval.starts_at
                for interval in snapshot.household_load_forecast.intervals
                if snapshot.captured_at
                < interval.starts_at
                < selected_horizon_end
            )
            boundaries.update(
                interval.ends_at
                for interval in snapshot.household_load_forecast.intervals
                if snapshot.captured_at < interval.ends_at < selected_horizon_end
            )
        if snapshot.captured_at < EXPORT_TAX_TRANSITION < selected_horizon_end:
            boundaries.add(EXPORT_TAX_TRANSITION)
        ordered = tuple(sorted(boundaries))
        intervals = tuple(
            self._interval(points, starts_at=left, ends_at=right)
            for left, right in zip(ordered, ordered[1:], strict=False)
        )
        return DailyReferenceTariffSchedule(
            schedule_id=f"daily-tariffs:{snapshot.snapshot_id}",
            snapshot_id=snapshot.snapshot_id,
            horizon_start=snapshot.captured_at,
            horizon_end=selected_horizon_end,
            intervals=intervals,
            method_version=METHOD_VERSION,
        )

    @staticmethod
    def _validate_coverage(
        points: tuple[PriceForecastPoint, ...],
        *,
        starts_at: datetime,
        ends_at: datetime,
    ) -> None:
        cursor = starts_at
        for point in points:
            if point.ends_at <= starts_at or point.starts_at >= ends_at:
                continue
            segment_start = max(point.starts_at, starts_at)
            segment_end = min(point.ends_at, ends_at)
            if segment_start != cursor or segment_end <= segment_start:
                raise DailyReferenceTariffInputError(
                    "daily_tariff_price_coverage_incomplete"
                )
            cursor = segment_end
        if cursor != ends_at:
            raise DailyReferenceTariffInputError(
                "daily_tariff_price_coverage_incomplete"
            )

    @staticmethod
    def _interval(
        points: tuple[PriceForecastPoint, ...],
        *,
        starts_at: datetime,
        ends_at: datetime,
    ) -> DailyReferenceTariffInterval:
        point = next(
            item
            for item in points
            if item.starts_at <= starts_at and item.ends_at >= ends_at
        )
        import_rate = point.value_eur_per_kwh
        export_rate = import_rate
        policy_evidence = "nl-net-metering-through-2026"
        if starts_at >= EXPORT_TAX_TRANSITION:
            bare_market_rate = import_rate - (
                ENERGY_TAX_EX_VAT_EUR_PER_KWH
                + SUPPLIER_ADDITION_EX_VAT_EUR_PER_KWH
            ) * VAT_FACTOR
            export_rate = bare_market_rate + EXPORT_ADDITION_EUR_PER_KWH
            policy_evidence = "nl-export-bare-market-plus-0.02-2027"
        return DailyReferenceTariffInterval(
            starts_at=starts_at,
            ends_at=ends_at,
            import_eur_per_kwh=import_rate,
            export_eur_per_kwh=export_rate,
            confidence=point.confidence,
            evidence_ids=(point.point_id, point.evidence_id, policy_evidence),
        )
