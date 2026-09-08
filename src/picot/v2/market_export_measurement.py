"""Attribute measured battery export from aligned HA power histories.

PV serves household demand first, as in the shared physical model. Simultaneous
battery discharge and net export are attributed by the lesser instantaneous
power, never by subtracting forecast household use or by taking an SOC delta.
"""

from datetime import datetime
from math import isfinite

from picot.v2.power_history import PowerHistorySnapshot


def measured_market_export(
    history: PowerHistorySnapshot | None, starts_at: datetime, ends_at: datetime
) -> float | None:
    if (
        history is None
        or history.status != "available"
        or not (history.starts_at <= starts_at <= ends_at <= history.ends_at)
    ):
        return None
    series = tuple(s for s in history.series if s.role in {"battery_discharge", "grid_export"})
    if len(series) != 2 or {s.role for s in series} != {"battery_discharge", "grid_export"}:
        return None
    if any(s.history_semantics != "state_hold" for s in series):
        return None
    initial = tuple(
        next(
            (
                p
                for p in sorted(s.points, key=lambda p: p.sampled_at, reverse=True)
                if p.sampled_at <= starts_at
            ),
            None,
        )
        for s in series
    )
    if any(p is None or not isfinite(p.power_w) or p.power_w < 0 for p in initial):
        return None
    boundaries = sorted(
        {starts_at, ends_at}
        | {p.sampled_at for s in series for p in s.points if starts_at < p.sampled_at < ends_at}
    )
    total = 0.0
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        points = tuple(
            next(
                (
                    p
                    for p in sorted(s.points, key=lambda p: p.sampled_at, reverse=True)
                    if p.sampled_at <= left
                ),
                None,
            )
            for s in series
        )
        if any(p is None or not isfinite(p.power_w) or p.power_w < 0 for p in points):
            return None
        total += (
            min(p.power_w for p in points if p is not None) * (right - left).total_seconds() / 3600
        )
    return total
