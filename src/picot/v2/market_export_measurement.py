"""Attribute measured battery export from aligned HA power histories.

PV serves household demand first, as in the shared physical model. Simultaneous
battery discharge and net export are attributed by the lesser instantaneous
power, never by subtracting forecast household use or by taking an SOC delta.
"""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from picot.v2.power_history import PowerHistorySnapshot

MAX_RECOVERED_MARKET_GAP_SECONDS = 2.0
MAX_MARKET_EXPORT_UNCERTAINTY_WH = 5.0


@dataclass(frozen=True, slots=True)
class BoundedMarketExport:
    """Valid measured energy and separate bounded estimates for recovered gaps."""

    measured_export_wh: float
    estimated_export_wh: float = 0.0
    uncertainty_wh: float = 0.0


def bounded_market_export(
    history: PowerHistorySnapshot | None,
    starts_at: datetime,
    ends_at: datetime,
    *,
    maximum_power_w: float,
) -> BoundedMarketExport | None:
    """Bridge only recovered gaps <=2 seconds, with <=5 Wh total uncertainty.

    Gap energy never enters measured_export_wh. The uncertainty is an upper
    bound on missing export, allowing the guard to enforce its budget safely.
    Open gaps, absent anchors and malformed/negative power remain failures.
    """
    if (history is None or history.status != "available"
            or not history.starts_at <= starts_at <= ends_at <= history.ends_at
            or not isfinite(maximum_power_w) or maximum_power_w <= 0):
        return None
    series = tuple(s for s in history.series if s.role in {"battery_discharge", "grid_export"})
    if (len(series) != 2 or {s.role for s in series} != {"battery_discharge", "grid_export"}
            or any(s.history_semantics != "state_hold" for s in series)):
        return None
    ordered = [sorted(s.points, key=lambda p: p.sampled_at) for s in series]
    estimates: list[dict[datetime, float]] = []
    for points in ordered:
        anchor = next((p for p in reversed(points) if p.sampled_at <= starts_at), None)
        if anchor is None or not isfinite(anchor.power_w) or anchor.power_w < 0:
            return None
        replacements: dict[datetime, float] = {}
        index = 0
        while index < len(points):
            point = points[index]
            if not starts_at < point.sampled_at < ends_at:
                index += 1
                continue
            if isfinite(point.power_w):
                if point.power_w < 0:
                    return None
                index += 1
                continue
            first = index
            while index < len(points) and not isfinite(points[index].power_w):
                index += 1
            if first == 0 or index == len(points):
                return None
            before, after = points[first - 1], points[index]
            if (after.sampled_at > ends_at or after.power_w < 0
                    or (after.sampled_at - point.sampled_at).total_seconds()
                    > MAX_RECOVERED_MARKET_GAP_SECONDS):
                return None
            estimate = min(maximum_power_w, (before.power_w + after.power_w) / 2)
            for missing_point in points[first:index]:
                replacements[missing_point.sampled_at] = estimate
        estimates.append(replacements)
    boundaries = sorted({starts_at, ends_at} | {
        p.sampled_at for points in ordered for p in points
        if starts_at < p.sampled_at < ends_at
    })
    indexes = [0, 0]
    measured = estimated = uncertainty = 0.0
    for left, right in zip(boundaries, boundaries[1:], strict=False):
        powers, upper = [], []
        missing = False
        for number, points in enumerate(ordered):
            while indexes[number] + 1 < len(points) and (
                points[indexes[number] + 1].sampled_at <= left
            ):
                indexes[number] += 1
            point = points[indexes[number]]
            if isfinite(point.power_w):
                powers.append(point.power_w)
                upper.append(point.power_w)
            else:
                replacement = estimates[number].get(point.sampled_at)
                if replacement is None:
                    return None
                missing = True
                powers.append(replacement)
                upper.append(maximum_power_w)
        hours = (right - left).total_seconds() / 3600
        if missing:
            estimated += min(powers) * hours
            uncertainty += min(maximum_power_w, *upper) * hours
            if uncertainty > MAX_MARKET_EXPORT_UNCERTAINTY_WH:
                return None
        else:
            measured += min(powers) * hours
    return BoundedMarketExport(measured, estimated, uncertainty)


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
