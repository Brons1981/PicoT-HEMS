"""Bounded financial estimates. Never amend raw evidence or planner inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from picot.v2.financial_result_metrics import financial_measurement_coverage
from picot.v2.power_history import PowerHistoryPoint, PowerHistorySeries, PowerHistorySnapshot
from picot.v2.review_alignment import FLOW_SIGNS, QUARTER_SECONDS, aligned_measurements
from picot.v2.sun_state_history import SunStateHistoryReadResult

MAX_GAP_SECONDS = 120.0
MAX_GAP_UNCERTAINTY_WH = 100.0
MAX_DAY_UNCERTAINTY_WH = 500.0


@dataclass(frozen=True)
class FinancialNightWindow:
    starts_at: datetime
    ends_at: datetime
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class FinancialInferredHistory:
    history: PowerHistorySnapshot
    inferences: tuple[dict[str, Any], ...]
    inferred_roles: frozenset[str]
    uncertainty_wh: float
    raw_coverage: dict[str, Any]
    rejected: tuple[dict[str, Any], ...]


def financial_night_windows(
    solar: SunStateHistoryReadResult, starts_at: datetime, ends_at: datetime,
) -> tuple[FinancialNightWindow, ...]:
    """Use recorded day/night states only inside the successfully read window."""
    if solar.status != "available" or solar.error or solar.source_entity_id != "sun.sun":
        return ()
    starts_at = max(starts_at.astimezone(UTC), solar.starts_at.astimezone(UTC))
    ends_at = min(ends_at.astimezone(UTC), solar.ends_at.astimezone(UTC))
    points = sorted((replace(p, sampled_at=p.sampled_at.astimezone(UTC))
                     for p in solar.observations), key=lambda p: p.sampled_at)
    if any(a.sampled_at == b.sampled_at and a.state != b.state
           for a, b in zip(points, points[1:], strict=False)):
        return ()
    result: list[FinancialNightWindow] = []
    for index, point in enumerate(points):
        following = points[index + 1] if index + 1 < len(points) else None
        start = max(starts_at, point.sampled_at)
        end = min(ends_at, following.sampled_at) if following else ends_at
        if point.state != "below_horizon" or not point.evidence_id or end <= start:
            continue
        evidence = (point.evidence_id, *((following.evidence_id,) if following else ()))
        if result and result[-1].ends_at == start:
            previous = result[-1]
            result[-1] = FinancialNightWindow(previous.starts_at, end,
                tuple(dict.fromkeys((*previous.evidence_ids, *evidence))))
        else:
            result.append(FinancialNightWindow(start, end, evidence))
    return tuple(result)


def _held(series: PowerHistorySeries, at: datetime) -> PowerHistoryPoint | None:
    return next((p for p in reversed(series.points) if p.sampled_at <= at), None)


def _replace_span(
    series: PowerHistorySeries, start: datetime, end: datetime, value: float, kind: str,
) -> PowerHistorySeries:
    """Replace only an explicitly admitted span in a separate immutable series."""
    after = _held(series, end)
    points = [p for p in series.points if p.sampled_at < start or p.sampled_at >= end]
    points.append(PowerHistoryPoint(start, value, f"financial:{kind}:{start.isoformat()}"))
    if not any(p.sampled_at == end for p in points):
        points.append(PowerHistoryPoint(
            end, after.power_w if after else float("nan"),
            after.evidence_id if after else "financial:missing-source",
        ))
    return replace(series, points=tuple(sorted(points, key=lambda p: p.sampled_at)))


def _event(role: str, kind: str, start: datetime, end: datetime, **extra: Any) -> dict[str, Any]:
    return {"role": role, "kind": kind, "starts_at": start.isoformat(),
            "ends_at": end.isoformat(), "duration_seconds": (end - start).total_seconds(), **extra}


def infer_financial_measurements(
    history: PowerHistorySnapshot, *, night_windows: tuple[FinancialNightWindow, ...] = (),
    pv_maximum_power_w: float, charge_maximum_power_w: float, discharge_maximum_power_w: float,
) -> FinancialInferredHistory:
    """Infer only admitted source gaps; retain all other missing evidence as missing."""
    history = replace(
        history, starts_at=history.starts_at.astimezone(UTC),
        ends_at=history.ends_at.astimezone(UTC),
        series=tuple(replace(s, points=tuple(replace(p, sampled_at=p.sampled_at.astimezone(UTC))
                                             for p in s.points)) for s in history.series),
    )
    raw_coverage = financial_measurement_coverage(history)
    if (history.status != "available" or history.error or history.ends_at <= history.starts_at
            or history.ends_at - history.starts_at > timedelta(hours=26)):
        return FinancialInferredHistory(history, (), frozenset(), 0.0, raw_coverage, ())
    series = {s.role: replace(s, points=tuple(sorted(s.points, key=lambda p: p.sampled_at)))
              for s in history.series}
    if len(series) != len(history.series):
        return FinancialInferredHistory(history, (), frozenset(), 0.0, raw_coverage, ())
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def view() -> PowerHistorySnapshot:
        return replace(history, series=tuple(series[s.role] for s in history.series))

    if "pv_generation" in series and not raw_coverage["pv_generation"]["omitted_gap_count"]:
        for gap in raw_coverage["pv_generation"]["gaps"]:
            lo, hi = (datetime.fromisoformat(gap[k]) for k in ("starts_at", "ends_at"))
            for window in night_windows:
                if not window.evidence_ids:
                    continue
                start, end = max(lo, window.starts_at), min(hi, window.ends_at)
                if end <= start:
                    continue
                series["pv_generation"] = _replace_span(
                    series["pv_generation"], start, end, 0.0, "night_zero",
                )
                events.append(_event("pv_generation", "night_zero", start, end,
                                     source_evidence_ids=list(window.evidence_ids)))

    bounds = {"pv_generation": pv_maximum_power_w, "battery_charge": charge_maximum_power_w,
              "battery_discharge": discharge_maximum_power_w}
    coverage = financial_measurement_coverage(view())
    candidates: list[dict[str, Any]] = []
    for role, maximum in bounds.items():
        if role not in series or coverage[role]["omitted_gap_count"]:
            continue
        for gap in coverage[role]["gaps"]:
            start, end = (datetime.fromisoformat(gap[k]) for k in ("starts_at", "ends_at"))
            before = next((p for p in reversed(series[role].points) if p.sampled_at < start), None)
            after = _held(series[role], end)
            reason = None
            if not isfinite(maximum) or maximum <= 0:
                reason = "physical_power_bound_missing"
            elif any(isfinite(p.power_w) and p.power_w > maximum for p in series[role].points):
                reason = "physical_power_bound_exceeded"
            elif (before is None or after is None or after.sampled_at < end
                  or not all(isfinite(p.power_w) and 0 <= p.power_w <= maximum
                             for p in (before, after))):
                reason = "gap_not_bounded_by_valid_measurements"
            elif (end - start).total_seconds() > MAX_GAP_SECONDS:
                reason = "gap_duration_limit_exceeded"
            if reason:
                rejected.append(_event(role, reason, start, end))
                continue
            assert before is not None and after is not None
            value = (before.power_w + after.power_w) / 2.0
            uncertainty = max(value, maximum - value) * (end - start).total_seconds() / 3600
            if uncertainty > MAX_GAP_UNCERTAINTY_WH:
                rejected.append(_event(role, "gap_energy_limit_exceeded", start, end))
                continue
            candidates.append(_event(
                role, "bounded_gap", start, end, estimated_power_w=value,
                maximum_power_w=maximum, uncertainty_wh=uncertainty,
                source_evidence_ids=[before.evidence_id, after.evidence_id],
            ))
    uncertainty = sum(item["uncertainty_wh"] for item in candidates)
    if uncertainty > MAX_DAY_UNCERTAINTY_WH:
        rejected.extend(dict(item, kind="daily_uncertainty_limit_exceeded") for item in candidates)
        candidates, uncertainty = [], 0.0
    for item in candidates:
        start, end = (datetime.fromisoformat(item[k]) for k in ("starts_at", "ends_at"))
        series[item["role"]] = _replace_span(
            series[item["role"]], start, end, item["estimated_power_w"], "bounded_gap",
        )
        events.append(item)

    household = series.get("household_load")
    gaps = raw_coverage["household_load"]
    if household is not None and not gaps["omitted_gap_count"] and set(FLOW_SIGNS) <= series.keys():
        # Explicit NaNs preserve all unresolved sampled gaps when the financial
        # copy changes to held interval averages. No stale sample bridges a hole.
        for gap in gaps["gaps"]:
            start, end = (datetime.fromisoformat(gap[k]) for k in ("starts_at", "ends_at"))
            household = _replace_span(household, start, end, float("nan"), "missing_household")
        household = replace(household, history_semantics="state_hold")
        gap_spans = [(datetime.fromisoformat(g["starts_at"]), datetime.fromisoformat(g["ends_at"]))
                     for g in gaps["gaps"]]
        aligned = aligned_measurements(view())
        for interval in aligned["intervals"]:
            lo, hi = (datetime.fromisoformat(interval[k]) for k in ("starts_at", "ends_at"))
            if not any(start < hi and end > lo for start, end in gap_spans):
                continue
            reason = interval["reason"]
            if (hi - lo).total_seconds() != QUARTER_SECONDS:
                reason = "household_quarter_not_closed"
            if reason:
                rejected.append(_event("household_load", reason, lo, hi,
                    balance_wh=interval["household_balance_wh"],
                    source_errors=interval["source_errors"]))
                continue
            balance = interval["household_energy_wh"]
            # One complete quarter replaces the financial copy once, including its
            # sampled fragments. Mixing those fragments with a gap-only balance
            # would reintroduce asynchronous sensor bias and double-count energy.
            household = _replace_span(
                household, lo, hi, balance * 3600 / QUARTER_SECONDS, "flow_balance",
            )
            if (events and events[-1]["kind"] == "flow_balance"
                    and events[-1]["ends_at"] == lo.isoformat()):
                events[-1]["ends_at"] = hi.isoformat()
                events[-1]["duration_seconds"] += QUARTER_SECONDS
                events[-1]["energy_wh"] += balance
            else:
                events.append(_event("household_load", "flow_balance", lo, hi,
                    source_roles=list(FLOW_SIGNS), energy_wh=balance,
                    interval_seconds=QUARTER_SECONDS, method_version=aligned["method_version"]))
        series["household_load"] = household
    return FinancialInferredHistory(
        view(), tuple(events), frozenset(item["role"] for item in events), uncertainty,
        raw_coverage, tuple(rejected),
    )
