"""Dutch calendar identities and retention classification, without deleting data."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def microseconds(value: str | datetime) -> int:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("history timestamps must be timezone-aware")
    delta = stamp.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def bounds(day: date) -> tuple[int, int]:
    return tuple(  # type: ignore[return-value]
        microseconds(datetime.combine(d, time.min, AMSTERDAM))
        for d in (day, day + timedelta(days=1))
    )


def retention_tier(day: date, today: date) -> str:
    age = (today - day).days
    if age < 0:
        return "future"
    if age <= 2:
        return "raw_replay"
    if age < 90:
        return "all_quarters"
    try:
        expiry = day.replace(year=day.year + 5)
    except ValueError:
        expiry = date(day.year + 5, 3, 1)
    return "long_term" if today < expiry else "review_required"
