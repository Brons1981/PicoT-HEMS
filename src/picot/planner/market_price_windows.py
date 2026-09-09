"""Unranked export alternatives with explicit fictitious import references.

No dispatch, commitment, recovery assignment, SOC eligibility or financial
net-profit claim is created here. Candidate/Evaluation retains those decisions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite

from picot.domain.daily_reference_tariff import DailyReferenceTariffSchedule
from picot.domain.market_user_rule import (
    MarketPricePart,
    MarketPriceWindow,
    MarketSpreadEvidence,
    MarketUserRule,
)
from picot.domain.storage_conversion_model import StorageConversionModel


def market_price_alternatives(
    *,
    rule: MarketUserRule,
    tariffs: DailyReferenceTariffSchedule,
    delivery_start: datetime,
    delivery_end: datetime,
    earliest_export: datetime,
    usable_capacity_wh: float,
    charge_power_w: float,
    discharge_power_w: float,
    conversion: StorageConversionModel,
) -> tuple[MarketSpreadEvidence, ...]:
    """Exact constant-power sliding windows on the published tariff steps.

    Extrema of the window integral occur when either endpoint touches a price
    boundary. Include both sets, plus the actual earliest permissible start.
    Return every export alternative; only the fictitious reference is minimised.
    Equal reference prices use the earliest interval solely for traceability;
    this does not schedule charging or choose the winning export candidate.
    """
    for at in (delivery_start, delivery_end, earliest_export):
        if at.utcoffset() is None:
            raise ValueError("market delivery and availability boundaries must be aware")
    if delivery_end <= delivery_start:
        raise ValueError("market delivery day must have positive duration")
    if not (tariffs.horizon_start <= delivery_start < delivery_end <= tariffs.horizon_end):
        raise ValueError("complete published delivery-day tariffs are required")
    for value in (usable_capacity_wh, charge_power_w, discharge_power_w):
        if isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError("market capacity and configured powers must be finite positive values")
    energy = usable_capacity_wh * rule.capacity_fraction
    export_wh = energy * conversion.discharge_efficiency
    import_wh = energy / conversion.charge_efficiency
    export_duration = timedelta(hours=export_wh / discharge_power_w)
    reference_duration = timedelta(hours=import_wh / charge_power_w)
    if export_duration <= timedelta(0) or reference_duration <= timedelta(0):
        raise ValueError("market duration is below timestamp resolution")

    def windows(
        duration: timedelta, power: float, start: datetime, *, fictitious: bool
    ) -> tuple[MarketPriceWindow, ...]:
        last_start = delivery_end - duration
        if last_start < start:
            return ()
        boundaries = {delivery_start, delivery_end}
        for interval in tariffs.intervals:
            if interval.starts_at < delivery_end and interval.ends_at > delivery_start:
                boundaries.update(
                    (max(interval.starts_at, delivery_start), min(interval.ends_at, delivery_end))
                )
        starts = {start, last_start}
        for boundary in boundaries:
            starts.update((boundary, boundary - duration))
        result = []
        for first in sorted(t for t in starts if start <= t <= last_start):
            end = first + duration
            parts = []
            for interval in tariffs.intervals:
                left, right = max(first, interval.starts_at), min(end, interval.ends_at)
                if right <= left:
                    continue
                price = (
                    interval.import_eur_per_kwh
                    if fictitious
                    else (
                        interval.cross_interval_export_eur_per_kwh
                        if interval.cross_interval_export_eur_per_kwh is not None
                        else interval.export_eur_per_kwh
                    )
                )
                parts.append(
                    MarketPricePart(
                        left,
                        right,
                        power * (right - left).total_seconds() / 3600,
                        price,
                        interval.evidence_ids,
                    )
                )
            window = MarketPriceWindow(tuple(parts), fictitious)
            if window.starts_at != first or window.ends_at != end:
                raise ValueError("market price window has incomplete published evidence")
            result.append(window)
        return tuple(result)

    references = windows(reference_duration, charge_power_w, delivery_start, fictitious=True)
    if not references:
        return ()
    reference = min(references, key=lambda w: (w.average_eur_per_kwh, w.starts_at))
    exports = windows(
        export_duration, discharge_power_w, max(delivery_start, earliest_export), fictitious=False
    )
    return tuple(
        MarketSpreadEvidence(
            rule.rule_id,
            rule.revision,
            tariffs.snapshot_id,
            energy,
            conversion.model_id,
            conversion.evidence_ids,
            charge_power_w,
            discharge_power_w,
            export,
            reference,
            rule.minimum_spread_eur_per_kwh,
        )
        for export in exports
    )
