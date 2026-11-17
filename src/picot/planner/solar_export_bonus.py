"""One deterministic solar-bonus formula for forecast and measured export."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from math import acos, asin, atan, cos, degrees, floor, radians, sin, tan
from zoneinfo import ZoneInfo

from picot.domain.solar_export_bonus import SolarExportBonusContext, SolarExportBonusPolicy

BONUS_FRACTION = 0.10
ANNUAL_EXPORT_LIMIT_KWH = 7500.0


def daylight(policy: SolarExportBonusPolicy, day: date) -> tuple[datetime, datetime] | None:
    """Conventional apparent sunrise/set, 90.833 degree zenith; no PV inference.

    The bounded astronomical approximation uses configured installation coordinates.
    Polar days without two events do not fabricate a bonus window.
    """

    def event(rising: bool) -> datetime | None:
        longitude_hour = policy.longitude / 15
        t = day.timetuple().tm_yday + ((6 if rising else 18) - longitude_hour) / 24
        mean = 0.9856 * t - 3.289
        longitude = (
            mean + 1.916 * sin(radians(mean)) + 0.020 * sin(2 * radians(mean)) + 282.634
        ) % 360
        right_ascension = degrees(atan(0.91764 * tan(radians(longitude)))) % 360
        right_ascension += floor(longitude / 90) * 90 - floor(right_ascension / 90) * 90
        right_ascension /= 15
        sin_declination = 0.39782 * sin(radians(longitude))
        denominator = cos(asin(sin_declination)) * cos(radians(policy.latitude))
        if abs(denominator) < 1e-12:
            return None
        angle = (
            cos(radians(90.833)) - sin_declination * sin(radians(policy.latitude))
        ) / denominator
        if not -1 <= angle <= 1:
            return None
        hour = degrees(acos(angle))
        hour = (360 - hour if rising else hour) / 15
        utc_hour = (hour + right_ascension - 0.06571 * t - 6.622 - longitude_hour) % 24
        return datetime.combine(day, time(), UTC) + timedelta(hours=utc_hour)

    sunrise, sunset = event(True), event(False)
    return (sunrise, sunset) if sunrise and sunset and sunrise < sunset else None


def bonus_boundaries(
    context: SolarExportBonusContext | None,
    start: datetime,
    end: datetime,
) -> tuple[datetime, ...]:
    if context is None or context.status != "available" or not context.policy.enabled:
        return ()
    policy = context.policy
    tz = ZoneInfo(policy.timezone_name)
    day, last = start.astimezone(tz).date(), end.astimezone(tz).date()
    boundaries = {policy.effective_from}
    if policy.annual_exported_at is not None:
        boundaries.add(policy.annual_exported_at)
    while day <= last:
        boundaries.add(datetime.combine(day, time(), tz))
        events = daylight(policy, day)
        if events:
            boundaries.update(events)
        day += timedelta(days=1)
    return tuple(sorted(at for at in boundaries if start < at < end))


def bonus_rate(
    context: SolarExportBonusContext | None,
    start: datetime,
    end: datetime,
    base_export_rate: float,
) -> float:
    if (
        context is None
        or context.status != "available"
        or not context.policy.enabled
        or end <= context.policy.effective_from
        or base_export_rate <= 0
    ):
        return 0.0
    policy = context.policy
    tz = ZoneInfo(policy.timezone_name)
    year = start.astimezone(tz).year
    allowances = dict(context.annual_remaining_kwh)
    if not allowances or (year <= max(allowances) and allowances.get(year, 0) <= 0):
        return 0.0
    events = daylight(policy, start.astimezone(tz).date())
    if events is None:
        return 0.0
    left = max(start, events[0], policy.effective_from)
    right = min(end, events[1])
    fraction = max(0.0, (right - left).total_seconds()) / (end - start).total_seconds()
    return base_export_rate * BONUS_FRACTION * fraction


class SolarBonusAllowance:
    """Per-trajectory quantity cap. All export uses the annual 7500 kWh allowance."""

    def __init__(self, context: SolarExportBonusContext | None) -> None:
        self.context = context
        self.remaining = dict(context.annual_remaining_kwh) if context else {}

    def value(self, start: datetime, end: datetime, exported_kwh: float, rate: float) -> float:
        context = self.context
        if (
            context is None
            or context.status != "available"
            or not context.policy.enabled
            or exported_kwh <= 0
            or end <= context.policy.effective_from
        ):
            return 0.0
        policy = context.policy
        if policy.annual_exported_at is not None and end <= policy.annual_exported_at:
            return 0.0
        year = start.astimezone(ZoneInfo(policy.timezone_name)).year
        known_years = dict(context.annual_remaining_kwh)
        # Future calendar years start with a fresh allowance; an unknown current
        # year never silently acquires a zero-used baseline.
        if year not in self.remaining and known_years and year > max(known_years):
            self.remaining[year] = ANNUAL_EXPORT_LIMIT_KWH
        remaining = self.remaining.get(year, 0.0)
        covered = min(remaining, exported_kwh)
        self.remaining[year] = max(0.0, remaining - exported_kwh)
        return covered * rate

    def potential_value(
        self,
        start: datetime,
        end: datetime,
        exported_kwh: float,
        rate: float,
    ) -> float:
        previous = dict(self.remaining)
        try:
            return self.value(start, end, exported_kwh, rate)
        finally:
            self.remaining = previous
